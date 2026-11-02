"""Verify the sample API and simulated database caller without services."""

from fastapi.testclient import TestClient
from examples import telemetry_api, telemetry_script


def test_api_example_success_and_failure(monkeypatch):
    """The two demonstration outcomes use ordinary HTTP status codes."""
    monkeypatch.setattr(telemetry_api, "initialize", lambda **_: False)
    monkeypatch.setattr(telemetry_api, "shutdown", lambda: True)
    with TestClient(telemetry_api.app) as client:
        assert client.get("/demo/operation").json() == {"status": "success", "example": "synthetic"}
        response = client.get("/demo/operation?fail=true")
        assert response.status_code == 503
        assert response.json()["status"] == "error"


def test_script_example_has_controlled_failure():
    """The script example performs no real database operation."""
    assert telemetry_script.run_simulated_read() is True
    assert telemetry_script.run_simulated_read(fail=True) is False
