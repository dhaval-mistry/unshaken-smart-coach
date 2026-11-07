"""HTTP contract tests for liveness and the shared response behavior (issue #12)."""

import os
import subprocess
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import health


@pytest.fixture
def client(monkeypatch):
    """Run the real app with telemetry replaced by do-nothing functions."""
    monkeypatch.setattr(main, "initialize", lambda **_: False)
    monkeypatch.setattr(main, "shutdown", lambda: True)
    # Return 500 responses instead of re-raising the crash inside the test.
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_shared_headers(response) -> str:
    """Every response is uncached JSON with a server-generated UUID request ID."""
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    request_id = response.headers["x-request-id"]
    UUID(request_id)  # Raises ValueError if this is not a valid UUID.
    return request_id


def assert_error(response, status_code: int, code: str) -> None:
    """Errors use the shared envelope, and body and header IDs match."""
    assert response.status_code == status_code
    request_id = assert_shared_headers(response)
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == request_id


def test_live_returns_alive(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert_shared_headers(response)


def test_each_request_gets_a_new_id(client):
    first = client.get("/health/live").headers["x-request-id"]
    second = client.get("/health/live").headers["x-request-id"]
    assert first != second


def test_caller_request_id_is_ignored(client):
    response = client.get("/health/live", headers={"X-Request-ID": "caller-chosen-id"})
    assert response.headers["x-request-id"] != "caller-chosen-id"


@pytest.mark.parametrize(
    "extra",
    [{"params": {"foo": "secret-query"}}, {"content": b"secret-body"}],
    ids=["query-parameter", "request-body"],
)
def test_unexpected_input_is_rejected(client, extra):
    response = client.request("GET", "/health/live", **extra)
    assert_error(response, 422, "invalid_request")
    assert "secret" not in response.text  # Submitted input is never echoed.


def test_unknown_path_returns_not_found(client):
    assert_error(client.get("/no-such-route"), 404, "not_found")


def test_wrong_method_keeps_allow_header(client):
    response = client.post("/health/live")
    assert_error(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"


def test_unexpected_failure_is_safe(client, monkeypatch):
    def broken(**_):
        raise RuntimeError(
            "password=hunter2 SELECT * FROM users "
            "postgresql://unshaken:secret@db.internal:5432/unshaken_smart_coach"
        )

    # A controlled crash: make the route's response model raise.
    monkeypatch.setattr(health, "LiveResponse", broken)
    response = client.get("/health/live")
    assert_error(response, 500, "internal_error")
    for private in (
        "hunter2",
        "SELECT",
        "Traceback",
        "RuntimeError",
        "postgresql://",
        "db.internal",
        ":5432",
    ):
        assert private not in response.text
        assert private not in str(response.headers)


def test_openapi_documents_exact_liveness_response(client):
    schema = client.get("/openapi.json").json()
    ref = schema["paths"]["/health/live"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    model = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert model["required"] == ["status"]
    assert model["properties"]["status"]["const"] == "alive"


def run_isolated(code: str, **env: str) -> subprocess.CompletedProcess:
    """Run code in a fresh Python process so imports and global telemetry are clean."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, **env},
    )


def test_import_and_liveness_do_not_load_database_code():
    code = """
import sys
from fastapi.testclient import TestClient
import app.main as main
main.initialize = lambda **_: False
main.shutdown = lambda: True
with TestClient(main.app) as client:
    assert client.get('/health/live').status_code == 200
loaded = [name for name in sys.modules if name.startswith('app.db')]
assert not loaded, loaded
"""
    result = run_isolated(code, DATABASE_URL="postgresql://nobody:wrong@127.0.0.1:1/missing")
    assert result.returncode == 0, result.stderr


def test_liveness_survives_unreachable_telemetry_exporter():
    code = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response = client.get('/health/live')
    assert response.status_code == 200, response.status_code
    assert response.json() == {'status': 'alive'}
"""
    # Port 9 has nothing listening, so every export attempt fails.
    result = run_isolated(
        code,
        OTEL_SDK_DISABLED="false",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:9",
    )
    assert result.returncode == 0, result.stderr