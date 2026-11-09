from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_wrong_password_gives_short_message_without_secrets(server_url):
    bad = server_url.set(password="definitely-wrong-password")
    env = {"DATABASE_URL": bad.render_as_string(hide_password=False), "PATH": "", "SYSTEMROOT": "C:\Windows"}
    result = subprocess.run([sys.executable, "-m", "app.db", "plan"], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 3
    assert "could not connect to" in result.stderr
    assert "definitely-wrong-password" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
