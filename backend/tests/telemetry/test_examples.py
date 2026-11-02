"""Verify the sample API and simulated database caller without services."""

import subprocess
import sys

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


def test_failure_spans_are_safe_for_examples_and_exceptions():
    """Use a separate process because SDK global providers can only be set once."""
    code = '''
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from app.telemetry import operation_span
from examples import telemetry_api, telemetry_script

exporter = InMemorySpanExporter()
provider = TracerProvider(shutdown_on_exit=False)
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
telemetry_api.initialize = lambda **kwargs: False
telemetry_api.shutdown = lambda: True
with TestClient(telemetry_api.app) as client:
    assert client.get('/demo/operation').status_code == 200
    assert client.get('/demo/operation?fail=true').status_code == 503
assert telemetry_script.run_simulated_read() is True
assert telemetry_script.run_simulated_read(fail=True) is False
try:
    with operation_span('lookup'):
        raise ValueError('private exception text')
except ValueError:
    pass
spans = [span for span in exporter.get_finished_spans() if span.name.startswith('unshaken.')]
assert [span.status.status_code for span in spans] == [StatusCode.UNSET, StatusCode.ERROR, StatusCode.UNSET, StatusCode.ERROR, StatusCode.ERROR], [(span.name, str(span.status.status_code)) for span in spans]
for span in (spans[1], spans[3], spans[4]):
    assert span.status.description is None
    assert span.attributes['error.type'] == 'operation_failed'
    assert not span.events
    assert 'private exception text' not in str(span.attributes)
provider.shutdown()
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
