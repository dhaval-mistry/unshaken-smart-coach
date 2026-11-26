"""Check the safe Compose contract without starting Docker services."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VALID_BACKEND_URL = (
    "postgresql://compose_test:synthetic@postgres:5432/compose_test"
)
_UNSET = object()


@unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is unavailable")
class ComposeConfigurationTests(unittest.TestCase):
    """Render configuration privately; the database itself is never started."""

    def render(self, password=None, backend_database_url=_UNSET):
        """Ignore private settings and return only synthetic configuration."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("POSTGRES_")}
        environment = {
            key: value
            for key, value in environment.items()
            if not key.startswith("BACKEND_")
        }
        if backend_database_url is not _UNSET:
            environment["BACKEND_CONTAINER_DATABASE_URL"] = backend_database_url
        environment["BACKEND_SOURCE_COMMIT"] = "test-commit"
        if password is not None:
            environment["POSTGRES_PASSWORD"] = password
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "empty.env"
            env_file.write_text("")
            result = subprocess.run(
                [
                    "docker", "compose", "--env-file", str(env_file),
                    "-f", str(ROOT / "compose.yaml"), "--profile", "observability",
                    "config", "--format", "json",
                ],
                capture_output=True, text=True, env=environment, timeout=30,
            )
        self.assertEqual(result.returncode, 0, "Compose configuration could not be rendered")
        return json.loads(result.stdout)["services"]

    def test_loopback_and_no_default_password(self):
        """An unset password stays empty and the port is limited to loopback."""
        postgres = self.render()["postgres"]
        self.assertEqual(postgres["environment"]["POSTGRES_PASSWORD"], "")
        self.assertEqual(postgres["ports"][0]["host_ip"], "127.0.0.1")

    def test_explicit_password_is_preserved(self):
        """A contributor's private setting is passed through unchanged."""
        postgres = self.render("test-only-value")["postgres"]
        self.assertEqual(postgres["environment"]["POSTGRES_PASSWORD"], "test-only-value")

    def test_backend_has_only_approved_runtime_environment(self):
        """The API receives no PostgreSQL initializer or future provider settings."""
        backend = self.render(backend_database_url=VALID_BACKEND_URL)["backend"]
        self.assertEqual(
            set(backend["environment"]),
            {"DATABASE_URL", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SDK_DISABLED"},
        )
        self.assertIn("@postgres:5432/", backend["environment"]["DATABASE_URL"])
        self.assertEqual(backend["environment"]["OTEL_SDK_DISABLED"], "true")
        self.assertEqual(
            backend["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"],
            "http://alloy:4318",
        )

    def test_backend_is_loopback_only_and_waits_for_healthy_postgres(self):
        """Compose ordering and exposure match the approved local boundary."""
        backend = self.render(backend_database_url=VALID_BACKEND_URL)["backend"]
        self.assertEqual(backend["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(
            backend["depends_on"]["postgres"]["condition"], "service_healthy"
        )
        self.assertNotIn("alloy", backend["depends_on"])
        health = " ".join(backend["healthcheck"]["test"])
        self.assertIn("/health/live", health)
        self.assertIn("'status': 'alive'", health)

    def test_backend_runtime_is_hardened_and_has_no_mounts(self):
        """The baseline is non-root, immutable and narrowly writable."""
        backend = self.render(backend_database_url=VALID_BACKEND_URL)["backend"]
        self.assertEqual(backend["user"], "10001:10001")
        self.assertTrue(backend["read_only"])
        self.assertEqual(backend["cap_drop"], ["ALL"])
        self.assertEqual(backend["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(backend["pids_limit"], 128)
        self.assertEqual(backend["mem_limit"], "536870912")
        self.assertEqual(backend["cpus"], 1.0)
        self.assertNotIn("volumes", backend)
        self.assertEqual(len(backend["tmpfs"]), 1)
        self.assertIn("size=64m", backend["tmpfs"][0])
        self.assertIn("noexec", backend["tmpfs"][0])

    def test_backend_build_uses_narrow_context_and_commit_tag(self):
        """Image provenance and build input stay local to the backend allowlist."""
        backend = self.render(backend_database_url=VALID_BACKEND_URL)["backend"]
        self.assertEqual(Path(backend["build"]["context"]), ROOT / "backend")
        self.assertEqual(backend["build"]["args"]["SOURCE_COMMIT"], "test-commit")
        self.assertEqual(backend["image"], "unshaken-backend:test-commit")

    def test_backend_context_is_deny_by_default(self):
        """Only reviewed source/resource extensions are explicitly admitted."""
        rules = (ROOT / "backend" / ".dockerignore").read_text().splitlines()
        active = [line for line in rules if line and not line.startswith("#")]
        self.assertEqual(active[0], "**")
        for required in (
            "!Dockerfile",
            "!app/**/*.py",
            "!migrations/**/*.py",
            "!migrations/**/*.mako",
            "!migrations/**/*.sql",
        ):
            self.assertIn(required, active)
        # Dockerignore uses last-match-wins. Host/private exclusions must stay
        # after all directory traversal and source/resource allowances.
        last_allowance = max(i for i, rule in enumerate(active) if rule.startswith("!"))
        for exclusion in ("**/__pycache__/", "**/*.py[cod]", "**/.env.*", "**/*.key"):
            self.assertGreater(active.index(exclusion), last_allowance)

    def test_backend_context_excludes_nested_host_artifacts(self):
        """BuildKit receives source/resources but no synthetic host-private files."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context"
            output = root / "output"
            context.mkdir()
            output.mkdir()
            shutil.copyfile(ROOT / "backend" / ".dockerignore", context / ".dockerignore")

            allowed = {
                "Dockerfile": "FROM scratch\nCOPY . /\n",
                "pyproject.toml": "[project]\nname='synthetic'\nversion='0'\n",
                "uv.lock": "synthetic lock\n",
                "alembic.ini": "[alembic]\n",
                "app/main.py": "VALUE = 'synthetic'\n",
                "app/nested/helper.py": "HELPER = True\n",
                "migrations/env.py": "# synthetic migration environment\n",
                "migrations/script.py.mako": "synthetic template\n",
                "migrations/versions/0001.py": "# synthetic revision\n",
                "migrations/versions/guard.sql": "SELECT 1;\n",
            }
            excluded = {
                "app/__pycache__/main.cpython-312.pyc": b"synthetic bytecode",
                "app/nested/.env": b"SYNTHETIC_PRIVATE_VALUE=not-a-secret",
                "app/nested/private.key": b"synthetic private key marker",
                "app/nested/debug.log": b"synthetic log marker",
                "app/nested/temp.tmp": b"synthetic temp marker",
                "migrations/versions/__pycache__/0001.cpython-312.pyc": b"synthetic bytecode",
                "migrations/versions/credentials.json": b'{"synthetic": true}',
            }

            for relative, content in allowed.items():
                target = context / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            for relative, content in excluded.items():
                target = context / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

            result = subprocess.run(
                [
                    "docker", "build", "--no-cache", "--quiet",
                    "--output", f"type=local,dest={output}", str(context),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in allowed:
                self.assertTrue((output / relative).is_file(), relative)
            for relative in excluded:
                self.assertFalse((output / relative).exists(), relative)

    def test_unrelated_model_works_with_backend_url_absent_or_empty(self):
        """PostgreSQL and observability configuration never requires backend setup."""
        for value in (_UNSET, ""):
            services = self.render(backend_database_url=value)
            self.assertIn("postgres", services)
            self.assertIn("alloy", services)
            self.assertEqual(services["backend"]["environment"]["DATABASE_URL"], "")

    def test_dockerfile_pins_inputs_and_starts_only_uvicorn(self):
        """The image is locked, explicitly copied, and never migrates on startup."""
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
        self.assertEqual(dockerfile.count("python:3.12.12-slim-bookworm@sha256:"), 2)
        self.assertIn("ghcr.io/astral-sh/uv:0.13.7@sha256:", dockerfile)
        self.assertNotIn("COPY .", dockerfile)
        self.assertNotIn("ADD ", dockerfile)
        self.assertIn(
            'ENTRYPOINT ["python", "-m", "app.container_entrypoint"]',
            dockerfile,
        )
        self.assertIn('CMD ["uvicorn", "app.main:app"', dockerfile)
        command = dockerfile.rsplit("CMD ", 1)[1]
        self.assertNotIn("alembic", command)
        self.assertNotIn("unshaken-db", command)
