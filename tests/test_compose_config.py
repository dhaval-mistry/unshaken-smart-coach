"""Check PostgreSQL Compose defaults without starting Docker services."""

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
        """Ignore private settings and return only an in-memory configuration."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("POSTGRES_")}
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
        return json.loads(result.stdout)["services"]["postgres"]

    def test_loopback_and_no_default_password(self):
        """An unset password stays empty and the port is limited to loopback."""
        postgres = self.render()
        self.assertEqual(postgres["environment"]["POSTGRES_PASSWORD"], "")
        self.assertEqual(postgres["ports"][0]["host_ip"], "127.0.0.1")

    def test_explicit_password_is_preserved(self):
        """A contributor's private setting is passed through unchanged."""
        self.assertEqual(self.render("test-only-value")["environment"]["POSTGRES_PASSWORD"], "test-only-value")
