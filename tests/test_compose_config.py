"""Check the safe Compose contract without starting Docker services."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is unavailable")
class ComposeConfigurationTests(unittest.TestCase):
    """Render configuration privately; the database itself is never started."""

    def render(self, password=None):
        """Ignore private settings and return only synthetic configuration."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("POSTGRES_")}
        environment = {
            key: value
            for key, value in environment.items()
            if not key.startswith("BACKEND_")
        }
        environment["BACKEND_CONTAINER_DATABASE_URL"] = (
            "postgresql://compose_test:synthetic@postgres:5432/compose_test"
        )
        environment["BACKEND_SOURCE_COMMIT"] = "test-commit"
        if password is not None:
            environment["POSTGRES_PASSWORD"] = password
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "empty.env"
            env_file.write_text("")
            result = subprocess.run(
                ["docker", "compose", "--env-file", str(env_file), "-f", str(ROOT / "compose.yaml"),
                 "config", "--format", "json"],
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
        backend = self.render()["backend"]
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
        backend = self.render()["backend"]
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
        backend = self.render()["backend"]
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
        backend = self.render()["backend"]
        self.assertEqual(Path(backend["build"]["context"]), ROOT / "backend")
        self.assertEqual(backend["build"]["args"]["SOURCE_COMMIT"], "test-commit")
        self.assertEqual(backend["image"], "unshaken-backend:test-commit")

    def test_backend_context_is_deny_by_default(self):
        """Only reviewed runtime inputs are admitted to the Docker context."""
        rules = (ROOT / "backend" / ".dockerignore").read_text().splitlines()
        active = [line for line in rules if line and not line.startswith("#")]
        self.assertEqual(active[0], "**")
        self.assertEqual(
            set(active[1:]),
            {
                "!Dockerfile",
                "!pyproject.toml",
                "!uv.lock",
                "!alembic.ini",
                "!app/",
                "!app/**",
                "!migrations/",
                "!migrations/**",
            },
        )

    def test_dockerfile_pins_inputs_and_starts_only_uvicorn(self):
        """The image is locked, explicitly copied, and never migrates on startup."""
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
        self.assertEqual(dockerfile.count("python:3.12.12-slim-bookworm@sha256:"), 2)
        self.assertIn("ghcr.io/astral-sh/uv:0.13.7@sha256:", dockerfile)
        self.assertNotIn("COPY .", dockerfile)
        self.assertNotIn("ADD ", dockerfile)
        self.assertIn('CMD ["uvicorn", "app.main:app"', dockerfile)
        command = dockerfile.rsplit("CMD ", 1)[1]
        self.assertNotIn("alembic", command)
        self.assertNotIn("unshaken-db", command)
