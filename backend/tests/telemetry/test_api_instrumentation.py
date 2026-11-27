"""Verify real HTTP middleware and shared telemetry with in-memory SDK exporters."""

import os
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[2]


def _run_isolated(code: str, **environment: str) -> subprocess.CompletedProcess:
    """Run global OpenTelemetry provider checks in a fresh Python process."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **environment},
    )


def test_real_lookup_routes_emit_safe_correlated_signals():
    """HTTP and mocked DB spans correlate without exporting raw request data."""
    code = r'''
import logging
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app import main
from app.api import lookups
from app.db.readiness import LookupResult, ReadinessState
from app.telemetry import database_read_span

span_exporter = InMemorySpanExporter()
tracer = TracerProvider(shutdown_on_exit=False)
tracer.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(tracer)
metric_reader = InMemoryMetricReader()
meter_provider = MeterProvider(metric_readers=[metric_reader], shutdown_on_exit=False)
metrics.set_meter_provider(meter_provider)
log_exporter = InMemoryLogRecordExporter()
logger_provider = LoggerProvider(shutdown_on_exit=False)
logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
logger = logging.getLogger("unshaken.telemetry")
logger.setLevel(logging.INFO)
handler = LoggingHandler(logger_provider=logger_provider)
logger.addHandler(handler)

class MockLookupResources:
    async def lookup(self, table_name):
        # This is deliberately an in-memory test double, not a database read.
        with database_read_span(table_name):
            if table_name == "exercise_categories":
                return LookupResult(
                    ReadinessState.READY,
                    ({"id": 1, "name": "Synthetic", "sort_order": 1},),
                    0.01,
                )
            return LookupResult(ReadinessState.DATABASE_UNAVAILABLE, (), 0.02)

lookups._get_database_resources = lambda _app: MockLookupResources()
main.initialize = lambda **_: False
main.shutdown = lambda: True
with TestClient(main.app) as client:
    success = client.get("/api/v1/exercise-categories", headers={"X-Request-ID": "caller-value"})
    failure = client.get("/api/v1/body-parts")
    invalid = client.get("/api/v1/body-parts", params={"note": "synthetic-private-input"})
    probes = [client.get("/health/live") for _ in range(3)]

assert success.status_code == 200
assert failure.status_code == 503
assert invalid.status_code == 422
assert all(response.status_code == 200 for response in probes)
responses = {
    response.headers["x-request-id"]: response.status_code
    for response in (success, failure, invalid)
}

logs = [
    item.log_record
    for item in log_exporter.get_finished_logs()
    if item.log_record.body == "http.request.completed"
]
assert len(logs) == 3, [entry.body for entry in log_exporter.get_finished_logs()]
for record in logs:
    attrs = record.attributes
    assert attrs["request_id"] in responses
    assert attrs["http.response.status_code"] == responses[attrs["request_id"]]
    assert record.trace_id != 0 and record.span_id != 0
    assert record.trace_id != int(attrs["request_id"].replace("-", ""), 16)
    assert attrs["http.route"] in {
        "/api/v1/exercise-categories",
        "/api/v1/body-parts",
    }
    assert "synthetic-private-input" not in str(attrs)

spans = span_exporter.get_finished_spans()
http_spans = [span for span in spans if span.name.startswith("HTTP ")]
db_spans = [span for span in spans if span.name == "database.read"]
assert len(http_spans) == 3, [
    (span.name, tuple(span.attributes)) for span in spans
]
assert len(db_spans) == 2  # Invalid input is rejected before the mocked read.
assert len(spans) == 5  # Native FastAPI spans and health-poll spans are disabled.
by_request = {span.attributes["request.id"]: span for span in http_spans}
for record in logs:
    parent = by_request[record.attributes["request_id"]]
    assert record.trace_id == parent.context.trace_id
    assert record.span_id == parent.context.span_id
assert all(span.attributes["db.system.name"] == "postgresql" for span in db_spans)
assert all(span.attributes["db.operation.name"] == "select" for span in db_spans)
assert all("db.statement" not in span.attributes for span in db_spans)
assert not any("synthetic-private-input" in str(span.attributes) for span in spans), [
    (span.name, tuple(span.attributes), [
        key for key, value in span.attributes.items()
        if "synthetic-private-input" in str(value)
    ])
    for span in spans
]
assert not any("caller-value" in str(span.attributes) for span in spans), [
    span.name for span in spans if "caller-value" in str(span.attributes)
]

metric_data = metric_reader.get_metrics_data()
metrics_found = {
    metric.name: metric
    for resource in metric_data.resource_metrics
    for scope in resource.scope_metrics
    for metric in scope.metrics
}
counter = metrics_found["unshaken.http.server.request.count"]
duration = metrics_found["unshaken.http.server.request.duration"]
assert counter.unit == "1"
assert duration.unit == "s"
counter_points = [point for point in counter.data.data_points]
duration_points = [point for point in duration.data.data_points]
assert sum(point.value for point in counter_points) == 6
lookup_points = [
    point for point in counter_points
    if point.attributes["http.route"].startswith("/api/v1/")
]
assert sum(point.value for point in lookup_points) == 3
assert {
    (point.attributes["http.route"], point.attributes["http.response.status_code"],
     point.attributes["failure.category"])
    for point in lookup_points
} == {
    ("/api/v1/exercise-categories", 200, "none"),
    ("/api/v1/body-parts", 503, "database_unavailable"),
    ("/api/v1/body-parts", 422, "invalid_request"),
}
assert all(
    set(point.attributes) == {
        "http.route",
        "http.request.method",
        "http.response.status_code",
        "failure.category",
    }
    for point in counter_points
)
assert all(point.attributes["http.request.method"] == "GET" for point in counter_points)
assert sum(point.count for point in duration_points) == 6
logger.removeHandler(handler)
logger_provider.shutdown()
meter_provider.shutdown()
tracer.shutdown()
'''
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr


def test_unexpected_lookup_error_has_matching_safe_telemetry_category():
    """Exercise middleware unwinding before the shared outer 500 handler."""
    code = r'''
import logging
from fastapi.testclient import TestClient
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from app import main
from app.api import lookups

reader = InMemoryMetricReader()
provider = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
metrics.set_meter_provider(provider)
records = []
class Capture(logging.Handler):
    def emit(self, record):
        if record.getMessage() == "http.request.completed":
            records.append(record)
handler = Capture()
logger = logging.getLogger("unshaken.telemetry")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
class BrokenResources:
    async def lookup(self, table):
        raise RuntimeError("synthetic-private-value")
lookups._get_database_resources = lambda app: BrokenResources()
main.initialize = lambda **kwargs: False
main.shutdown = lambda: True
with TestClient(main.app, raise_server_exceptions=False) as client:
    response = client.get("/api/v1/exercise-categories")
assert response.status_code == 500
assert response.json()["error"]["code"] == "internal_error"
assert len(records) == 1
assert records[0].__dict__["failure.category"] == "internal_error"
assert "synthetic-private-value" not in str(records[0].__dict__)
points = [point for resource in reader.get_metrics_data().resource_metrics
          for scope in resource.scope_metrics for metric in scope.metrics
          for point in metric.data.data_points]
assert points
assert all(point.attributes["failure.category"] == "internal_error" for point in points)
logger.removeHandler(handler)
provider.shutdown()
'''
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr


def test_lookup_responses_survive_disabled_and_unavailable_exporters():
    """The actual API response path is independent of telemetry destinations."""
    code = r'''
from fastapi.testclient import TestClient
from app import main
from app.api import health, lookups
from app.db.readiness import LookupResult, ReadinessResult, ReadinessState

class Resources:
    async def lookup(self, _table):
        return LookupResult(ReadinessState.READY, (), 0.01)
    async def check(self):
        return ReadinessResult(ReadinessState.READY, 0.01)
    def record_state(self, _result, _request_id):
        pass

resources = Resources()
lookups._get_database_resources = lambda _app: resources
health._get_database_readiness = lambda _app: resources
with TestClient(main.app) as client:
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v1/exercise-categories").status_code == 200
    assert client.get("/api/v1/body-parts").status_code == 200
'''
    disabled = _run_isolated(code, OTEL_SDK_DISABLED="true")
    assert disabled.returncode == 0, disabled.stderr
    unavailable = _run_isolated(
        code,
        OTEL_SDK_DISABLED="false",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:9",
    )
    assert unavailable.returncode == 0, unavailable.stderr


def test_readiness_exports_only_state_transitions():
    """Repeated probes in one state do not create repeated readiness logs."""
    code = r'''
import logging
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from app.db.readiness import DatabaseReadiness, ReadinessResult, ReadinessState

exporter = InMemoryLogRecordExporter()
provider = LoggerProvider(shutdown_on_exit=False)
provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
logger = logging.getLogger("unshaken.telemetry")
logger.setLevel(logging.INFO)
handler = LoggingHandler(logger_provider=provider)
logger.addHandler(handler)
resources = DatabaseReadiness(None)
resources.record_state(
    ReadinessResult(ReadinessState.DATABASE_UNAVAILABLE, 0.01),
    "00000000-0000-0000-0000-000000000001",
)
resources.record_state(
    ReadinessResult(ReadinessState.DATABASE_UNAVAILABLE, 0.01),
    "00000000-0000-0000-0000-000000000002",
)
resources.record_state(
    ReadinessResult(ReadinessState.READY, 0.01),
    "00000000-0000-0000-0000-000000000003",
)
records = [
    item.log_record
    for item in exporter.get_finished_logs()
    if item.log_record.body == "database_readiness.state_changed"
]
assert len(records) == 2
assert records[0].attributes["readiness_state"] == "database_unavailable"
assert records[0].attributes["request_id"] == "00000000-0000-0000-0000-000000000001"
assert records[1].attributes["readiness_state"] == "ready"
assert records[1].attributes["request_id"] == "00000000-0000-0000-0000-000000000003"
assert not any("exception" in item.log_record.attributes for item in exporter.get_finished_logs())
logger.removeHandler(handler)
provider.shutdown()
resources.shutdown()
'''
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
