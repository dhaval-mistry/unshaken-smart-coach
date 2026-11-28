"""Verify 429 through Caddy using a fresh synthetic Compose project."""

import hashlib
import hmac
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE_KEY = "synthetic-auth-proxy-key"


def compose(overrides, env_file, project, environment, *args, check=True, input_text=None):
    """Run Compose with explicit files and synthetic settings."""
    return subprocess.run(
        ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
         "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.auth.yaml"),
         "-f", str(overrides), *args],
        cwd=ROOT, env=environment, input=input_text, capture_output=True, text=True,
        timeout=180, check=check,
    )


def source_digest(address):
    """Derive the test window key for a synthetic loopback source."""
    return hmac.digest(SOURCE_KEY.encode(), f"unshaken:auth-source:v1:{address}".encode(),
                       hashlib.sha256).hex()


def verify():
    """Saturate isolated limiter rows and verify the proxied response."""
    import json

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
            "  backend:\n    ports: !reset []\n"
        )
        if os.name != "nt":
            settings.chmod(0o600)
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(("BACKEND_", "POSTGRES_", "USC_AUTH_", "COMPOSE_"))}
        environment.update(
            USC_LOCAL_AUTH_FILE=str(settings),
            BACKEND_SOURCE_COMMIT=project,
            BACKEND_CONTAINER_DATABASE_URL=(
                f"postgresql://fixture:synthetic@postgres:5432/{project.replace('-', '_')}"
            ),
            POSTGRES_USER="fixture", POSTGRES_DB=project.replace("-", "_"),
            POSTGRES_PASSWORD="synthetic",
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

            # Prepare the normal threshold directly in the fixture database.
            # One synthetic request then checks the public edge behavior.
            values = ", ".join(
                f"(decode('{source_digest(ip)}','hex'), now()+interval '5 minutes', 10)"
                for ip in ("127.0.0.1", "::1")
            )
            run("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
                "-U", "fixture", "-d", environment["POSTGRES_DB"],
                input_text="INSERT INTO auth_source_windows VALUES " + values + ";")
            run("up", "-d", "--no-deps", "caddy")

            import time

            probe = '''
import os
import ssl
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the fixture request entirely inside its local Compose project."""

    def redirect_request(self, request, response, code, message, headers, target):
        """Reject any redirect, including an unexpected Google redirect."""
        return None


opener = urllib.request.build_opener(
    NoRedirect(),
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ssl.create_default_context(cadata=os.environ["FIXTURE_CA"])),
)
try:
    opener.open("https://localhost:8443/api/v1/auth/google/start", timeout=2)
except urllib.error.HTTPError as response:
    if response.code == 429 and response.headers.get("Retry-After") == "300":
        print("limited")
'''
            for _ in range(20):
                certificate = run(
                    "exec", "-T", "caddy", "cat",
                    "/data/caddy/pki/authorities/local/root.crt", check=False,
                )
                if certificate.returncode == 0:
                    response = run(
                        "exec", "-T", "-e", f"FIXTURE_CA={certificate.stdout}",
                        "backend", "python", "-", input_text=probe, check=False,
                    )
                    if response.returncode == 0 and response.stdout.strip() == "limited":
                        print("PASS: local Caddy preserved HTTP 429 and Retry-After from FastAPI.")
                        return
                time.sleep(0.25)
            raise RuntimeError("The isolated proxy did not return HTTP 429 and Retry-After")
        finally:
            run("down", "--volumes", check=False)
            subprocess.run(["docker", "image", "rm", f"unshaken-backend:{project}"],
                           cwd=ROOT, capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    try:
        verify()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        # Do not display Compose output or synthetic callback details.
        print(f"Proxy verification failed ({type(error).__name__}).")
        raise SystemExit(1) from None
