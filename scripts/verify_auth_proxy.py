"""Check source attribution and HTTP 429 through disposable Caddy HTTPS."""

import hmac
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE_KEY = "synthetic-auth-proxy-key"
PEER_PORT = 18081
FORWARDED_FIXTURE = "192.0.2.47"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep all verification requests inside the local fixture."""

    def redirect_request(self, request, response, code, message, headers, target):
        """Reject external redirects without contacting an identity provider."""
        return None


class CleanupError(RuntimeError):
    """A disposable project's cleanup failed."""

    def __init__(self, project, operation):
        """Keep only the nonsecret project and failed operation."""
        self.project = project
        self.operation = operation
        super().__init__(f"{operation} failed for isolated project {project}")


def compose(overrides, env_file, project, environment, *args, input_text=None):
    """Run Compose with explicit files and synthetic settings."""
    return subprocess.run(
        ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
         "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.auth.yaml"),
         "-f", str(overrides), *args],
        cwd=ROOT, env=environment, input=input_text, capture_output=True, text=True,
        timeout=180, check=True,
    )


def cleanup(run, project):
    """Fail verification if Compose or the test image cannot be cleaned up."""
    try:
        run("down", "--volumes")
    except (OSError, subprocess.SubprocessError) as error:
        raise CleanupError(project, "Compose cleanup") from error
    try:
        image = subprocess.run(
            ["docker", "image", "ls", "--quiet", f"unshaken-backend:{project}"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        )
        if image.stdout.strip():
            subprocess.run(
                ["docker", "image", "rm", f"unshaken-backend:{project}"],
                cwd=ROOT, capture_output=True, timeout=30, check=True,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise CleanupError(project, "Image cleanup") from error


def source_digest(address):
    """Derive the fixture window key for a verified source address."""
    return hmac.digest(SOURCE_KEY.encode(), f"unshaken:auth-source:v1:{address}".encode(),
                       "sha256").hex()


def retry(operation):
    """Wait for a disposable listener or public CA to become available."""
    for attempt in range(20):
        try:
            return operation()
        except (OSError, subprocess.CalledProcessError):
            if attempt == 19:
                raise
            time.sleep(0.25)


def published_port(run, target):
    """Read the generated IPv4 loopback port without assuming a fixed port."""
    binding = run("port", "backend", str(target)).stdout.strip()
    match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", binding)
    if match is None:
        raise RuntimeError("Fixture endpoint is not published on IPv4 loopback")
    return int(match[1])


def measured_peer(run):
    """Measure the TCP source reaching the container from a host loopback client."""
    probe = (
        "import socket\n"
        "with socket.socket() as listener:\n"
        f"    listener.bind(('0.0.0.0', {PEER_PORT}))\n"
        "    listener.settimeout(10)\n"
        "    listener.listen(1)\n"
        "    connection, peer = listener.accept()\n"
        "    with connection:\n"
        "        connection.sendall(peer[0].encode('ascii'))\n"
    )
    run("exec", "-d", "backend", "python", "-c", probe)
    port = published_port(run, PEER_PORT)

    def receive():
        """Read the address reported by the one-shot fixture listener."""
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            address = connection.recv(80).decode("ascii")
            if not address:
                raise OSError("Fixture listener did not return its address")
            return ipaddress.ip_address(address)

    return retry(receive)


def check_published_https(run, database):
    """Compare the measured Docker peer with the limiter key after proxied requests."""
    peer = measured_peer(run)
    key = source_digest(str(peer))
    certificate = retry(lambda: run(
        "exec", "-T", "caddy", "cat", "/data/caddy/pki/authorities/local/root.crt",
    )).stdout
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cadata=certificate)),
    )
    url = f"https://localhost:{published_port(run, 8443)}/api/v1/auth/google/start"

    def request(headers=None):
        """Read status and retry policy without following provider redirects."""
        try:
            with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=2) as result:
                return result.status, result.headers.get("Retry-After")
        except urllib.error.HTTPError as result:
            with result:
                return result.code, result.headers.get("Retry-After")

    def sql(statement):
        """Read or write only the dedicated disposable fixture database."""
        return run("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-At",
                   "-U", "fixture", "-d", database, input_text=statement).stdout.strip()

    if retry(request) != (303, None):
        raise RuntimeError("Published HTTPS did not start a fixture sign-in")
    windows = "SELECT encode(source_hash, 'hex') || ':' || attempts FROM auth_source_windows;"
    if sql(windows) != f"{key}:1":
        raise RuntimeError("The limiter key did not match the measured Docker peer")
    # A reserved documentation address is inert fixture data. The proxy must
    # attribute the request to the same measured peer and retain one window.
    if request({"X-Forwarded-For": FORWARDED_FIXTURE}) != (303, None):
        raise RuntimeError("Published HTTPS did not accept the second fixture start")
    if sql(windows) != f"{key}:2":
        raise RuntimeError("Client-supplied forwarding changed the limiter window")

    sql(f"UPDATE auth_source_windows SET attempts = 10 WHERE source_hash = decode('{key}', 'hex');")
    if request({"X-Forwarded-For": FORWARDED_FIXTURE}) != (429, "300"):
        raise RuntimeError("Published HTTPS did not preserve HTTP 429 and Retry-After")
    if sql(windows) != f"{key}:10":
        raise RuntimeError("Rate-limited request changed the measured source window")
    return "loopback" if peer.is_loopback else "Docker network peer"


def verify():
    """Provision isolated PostgreSQL and confirm published Caddy behavior."""
    project = f"usc-proxy-test-{uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="usc-proxy-test-") as scratch:
        path = Path(scratch)
        settings = path / "synthetic.json"
        settings.write_text(json.dumps({
            "origin": "https://localhost:8443",
            "google_client_id": "synthetic",
            "google_client_secret": SOURCE_KEY,
        }))
        env_file = path / "empty.env"
        env_file.write_text("")
        overrides = path / "disposable.yaml"
        overrides.write_text(
            f"services:\n  postgres:\n    container_name: {project}-postgres\n"
            "    ports: !reset []\n    volumes: !reset []\n"
            f"  backend:\n    ports: !override\n"
            f"      - '127.0.0.1::8443'\n      - '127.0.0.1::{PEER_PORT}'\n"
        )
        if os.name != "nt":
            settings.chmod(0o600)
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(("BACKEND_", "POSTGRES_", "USC_AUTH_", "COMPOSE_"))}
        database = project.replace("-", "_")
        environment.update(
            USC_LOCAL_AUTH_FILE=str(settings),
            BACKEND_SOURCE_COMMIT=project,
            BACKEND_CONTAINER_DATABASE_URL=f"postgresql://fixture:synthetic@postgres:5432/{database}",
            POSTGRES_USER="fixture", POSTGRES_DB=database, POSTGRES_PASSWORD="synthetic",
        )
        if os.name != "nt":
            environment["USC_AUTH_BACKEND_USER"] = f"{os.getuid()}:{os.getgid()}"

        def run(*args, **kwargs):
            """Scope all project operations to this invocation's unique name."""
            return compose(overrides, env_file, project, environment, *args, **kwargs)

        try:
            run("up", "-d", "--wait", "postgres")
            run("up", "-d", "--no-deps", "--build", "--wait", "backend")
            planned = run("exec", "-T", "backend", "unshaken-db", "plan").stdout
            match = re.search(r"^Target confirmation token: ([0-9a-f]{20})$", planned, re.M)
            if match is None:
                raise RuntimeError("The disposable database plan did not return a confirmation token")
            run("exec", "-T", "backend", "unshaken-db", "upgrade", "--approve-target", match[1])
            run("up", "-d", "--no-deps", "caddy")
            peer_kind = check_published_https(run, database)
        finally:
            cleanup(run, project)
    print(f"PASS: host HTTPS grouped by {peer_kind}, ignored client forwarding,"
          " preserved HTTP 429 and Retry-After, and cleaned up.")


def main():
    """Report sanitized verification failures with a safe cleanup handoff."""
    try:
        verify()
    except CleanupError as error:
        print(f"Proxy verification failed: {error}.")
        label = f"label=com.docker.compose.project={error.project}"
        print(f"Inspect only this fixture: docker ps -a --filter {label}")
        print(f"Inspect its volumes: docker volume ls --filter {label}")
        print(f"Inspect its network: docker network ls --filter {label}")
        return 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        # Never display raw Compose output or callback details.
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        print(f"Proxy verification failed: {detail}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
