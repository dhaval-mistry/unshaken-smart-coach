"""Container startup rejects unsafe configuration before executing Uvicorn."""

import pytest

from app import container_entrypoint


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "not-a-url",
        "postgresql://APP_USER:ENCODED_PASSWORD@postgres:5432/APP_DATABASE",
        "postgresql://user:password@127.0.0.1:5432/database",
        "postgresql://user:password@postgres:5433/database",
    ],
)
def test_invalid_database_url_refuses_without_exec(value, monkeypatch, capsys):
    """Missing, example, loopback, and wrong-port targets fail without disclosure."""
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)
    monkeypatch.setattr(
        container_entrypoint.os,
        "execvp",
        lambda *_: pytest.fail("invalid configuration must not execute a command"),
    )

    assert container_entrypoint.main(["uvicorn"]) == 2
    error = capsys.readouterr().err
    assert error == (
        "Backend container refused to start: DATABASE_URL must be a private "
        "PostgreSQL URL for postgres:5432.\n"
    )
    if value:
        assert value not in error


def test_valid_database_url_execs_exact_command(monkeypatch):
    """A concrete private target replaces the entrypoint with the requested command."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://synthetic_user:synthetic_password@postgres:5432/synthetic_db",
    )
    observed = {}

    def capture_exec(executable, command):
        observed["executable"] = executable
        observed["command"] = command

    monkeypatch.setattr(container_entrypoint.os, "execvp", capture_exec)
    command = ["uvicorn", "app.main:app", "--no-access-log"]

    assert container_entrypoint.main(command) is None
    assert observed == {"executable": "uvicorn", "command": command}
