"""Tests for safe helper behavior and configuration without network calls."""

import logging
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from app.telemetry import logging as telemetry_logging
from app.telemetry import metrics as telemetry_metrics
from app.telemetry import setup


def test_safe_events_and_labels(caplog):
    """Unknown event text and sensitive values never become a log message or label."""
    with caplog.at_level(logging.INFO, logger="unshaken.telemetry"):
        telemetry_logging.log_event("secret medical note", operation="alice@example.org", outcome="12345")
        telemetry_logging.log_event("operation.completed", operation="alice@example.org", outcome="12345")
    assert [record.message for record in caplog.records] == ["operation.completed"]
    assert caplog.records[0].operation == "other"
    assert caplog.records[0].outcome == "other"
    assert "alice@example.org" not in caplog.text


def test_metrics_use_bounded_labels_and_seconds(monkeypatch):
    """The two instruments receive only known label values and valid durations."""
    meter = Mock()
    monkeypatch.setattr(telemetry_metrics.metrics, "get_meter", lambda _: meter)
    telemetry_metrics.record_operation("lookup", "success", 0.25)
    meter.create_counter.return_value.add.assert_called_once_with(1, {"operation": "lookup", "outcome": "success"})
    meter.create_histogram.return_value.record.assert_called_once_with(0.25, {"operation": "lookup", "outcome": "success"})
    meter.create_histogram.assert_called_once_with("unshaken.operation.duration", unit="s")
    telemetry_metrics.record_operation("lookup", "success", float("nan"))
    assert meter.create_histogram.return_value.record.call_count == 1


def test_endpoint_base_and_signal_override(monkeypatch):
    """Base URLs get a signal path, while explicit signal URLs remain unchanged."""
    monkeypatch.setattr(setup, "_setting", lambda key, default="": {
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318/base",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/custom/logs",
    }.get(key, default))
    assert setup._endpoint("metrics") == "http://localhost:4318/base/v1/metrics"
    assert setup._endpoint("logs") == "http://localhost:4318/custom/logs"


def test_disabled_and_invalid_configuration_do_not_raise(monkeypatch):
    """Disabled telemetry and a rejected service name leave the caller running."""
    monkeypatch.setattr(setup, "_providers", None)
    monkeypatch.setattr(setup, "_finished", False)
    assert setup.initialize(enabled=False) is False
    assert setup.initialize(service="private-user-input", enabled=True) is False


def test_initialize_twice_installs_one_handler(monkeypatch):
    """Repeated initialization reuses the existing provider set."""
    monkeypatch.setattr(setup, "_providers", None)
    monkeypatch.setattr(setup, "_finished", False)
    monkeypatch.setattr(setup, "_endpoint", lambda signal: "http://localhost:4318/v1/" + signal)
    monkeypatch.setattr(setup, "TracerProvider", Mock())
    monkeypatch.setattr(setup, "MeterProvider", Mock())
    monkeypatch.setattr(setup, "LoggerProvider", Mock())
    monkeypatch.setattr(setup, "OTLPSpanExporter", Mock())
    monkeypatch.setattr(setup, "OTLPMetricExporter", Mock())
    monkeypatch.setattr(setup, "OTLPLogExporter", Mock())
    monkeypatch.setattr(setup, "BatchSpanProcessor", Mock())
    monkeypatch.setattr(setup, "BatchLogRecordProcessor", Mock())
    monkeypatch.setattr(setup, "PeriodicExportingMetricReader", Mock())
    handler = logging.NullHandler()
    monkeypatch.setattr(setup, "LoggingHandler", lambda **_: handler)
    monkeypatch.setattr(setup.trace, "set_tracer_provider", Mock())
    monkeypatch.setattr(setup.metrics, "set_meter_provider", Mock())
    assert setup.initialize(enabled=True)
    assert setup.initialize(enabled=True)
    assert setup.LOGGER.handlers.count(handler) == 1
    assert setup.shutdown()


def test_exporter_setup_failure_is_safe(monkeypatch):
    """A failed exporter does not propagate its exception to the application."""
    monkeypatch.setattr(setup, "_providers", None)
    monkeypatch.setattr(setup, "_finished", False)
    monkeypatch.setattr(setup, "_endpoint", lambda _: (_ for _ in ()).throw(ValueError("private")))
    assert setup.initialize(enabled=True) is False


def _mock_startup(monkeypatch):
    """Replace SDK constructors so tests can observe ownership without threads."""
    monkeypatch.setattr(setup, "_providers", None)
    monkeypatch.setattr(setup, "_finished", False)
    monkeypatch.setattr(setup, "_endpoint", lambda signal: "http://localhost:4318/v1/" + signal)
    names = ("TracerProvider", "MeterProvider", "LoggerProvider", "OTLPSpanExporter", "OTLPMetricExporter",
             "OTLPLogExporter", "BatchSpanProcessor", "BatchLogRecordProcessor", "PeriodicExportingMetricReader")
    factories = {name: Mock() for name in names}
    for name, factory in factories.items():
        monkeypatch.setattr(setup, name, factory)
    handler = logging.NullHandler()
    monkeypatch.setattr(setup, "LoggingHandler", lambda **_: handler)
    monkeypatch.setattr(setup.trace, "set_tracer_provider", Mock())
    monkeypatch.setattr(setup.metrics, "set_meter_provider", Mock())
    return factories, handler


@pytest.mark.parametrize(("failed_factory", "resources"), [
    ("BatchSpanProcessor", ("TracerProvider", "OTLPSpanExporter")),
    ("MeterProvider", ("TracerProvider", "PeriodicExportingMetricReader")),
    ("OTLPLogExporter", ("TracerProvider", "MeterProvider", "LoggerProvider")),
])
def test_partial_initialization_cleans_up_and_can_retry(monkeypatch, failed_factory, resources):
    """Failures before global registration close owned resources before retrying."""
    factories, handler = _mock_startup(monkeypatch)
    factories[failed_factory].side_effect = RuntimeError("private test detail")
    assert setup.initialize(enabled=True) is False
    for name in resources:
        factories[name].return_value.shutdown.assert_called_once()
    assert handler not in setup.LOGGER.handlers
    assert setup._finished is False
    factories[failed_factory].side_effect = None
    assert setup.initialize(enabled=True) is True
    assert setup.shutdown() is True


def test_failed_global_registration_detaches_handler_and_disables_retry(monkeypatch):
    """Once registration starts, retry could reuse an already installed global."""
    factories, handler = _mock_startup(monkeypatch)
    setup.metrics.set_meter_provider.side_effect = RuntimeError("private test detail")
    assert setup.initialize(enabled=True) is False
    assert handler not in setup.LOGGER.handlers
    assert setup._finished is True
    for name in ("TracerProvider", "MeterProvider", "LoggerProvider"):
        factories[name].return_value.shutdown.assert_called_once()
    assert setup.initialize(enabled=True) is False


def test_slow_startup_cleanup_prevents_retry(monkeypatch):
    """A still-running cleanup worker blocks another installation attempt."""
    factories, _ = _mock_startup(monkeypatch)
    factories["OTLPSpanExporter"].side_effect = RuntimeError("failure")
    worker = Mock()
    worker.is_alive.return_value = True
    monkeypatch.setattr(setup, "Thread", Mock(return_value=worker))
    assert setup.initialize(enabled=True) is False
    worker.join.assert_called_once_with(3.0)
    assert setup._finished is True
    assert setup.initialize(enabled=True) is False


def test_failed_resource_cleanup_prevents_retry(monkeypatch):
    """A cleanup error leaves ownership uncertain, so initialization stays off."""
    factories, _ = _mock_startup(monkeypatch)
    factories["OTLPSpanExporter"].side_effect = RuntimeError("startup failed")
    factories["TracerProvider"].return_value.shutdown.side_effect = RuntimeError("cleanup failed")
    assert setup.initialize(enabled=True) is False
    assert setup._finished is True
    assert setup.initialize(enabled=True) is False


def test_import_does_not_open_network_connection():
    """Importing the helper package does not connect to Alloy."""
    code = "import socket; socket.socket.connect=lambda *args: (_ for _ in ()).throw(RuntimeError('network')); import app.telemetry; print('imported')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "imported" in result.stdout


def test_shutdown_has_one_shared_deadline(monkeypatch):
    """A stuck exporter cannot make the application wait without a limit."""
    provider = Mock()
    provider.force_flush.side_effect = lambda **_: time.sleep(0.2)
    handler = logging.NullHandler()
    monkeypatch.setattr(setup, "_providers", (provider, provider, provider, handler))
    monkeypatch.setattr(setup, "_finished", False)
    start = time.monotonic()
    assert setup.shutdown(timeout_seconds=0.01) is False
    assert time.monotonic() - start < 0.15


def test_shutdown_reports_failed_flush_and_still_closes(monkeypatch):
    """A fast but unsuccessful export is not reported as a successful shutdown."""
    providers = [Mock() for _ in range(3)]
    for provider in providers:
        provider.force_flush.return_value = True
    providers[1].force_flush.return_value = False
    # Replace external resources with mocks: this test never contacts Alloy.
    monkeypatch.setattr(setup, "_providers", (*providers, logging.NullHandler()))
    monkeypatch.setattr(setup, "_finished", False)
    assert setup.shutdown() is False
    for provider in providers:
        provider.shutdown.assert_called_once()


def test_real_sdk_correlates_safe_log_with_span():
    """Exercise actual SDK records in memory, without exporting or opening sockets."""
    # OpenTelemetry global providers are intentionally installed once per process.
    # A child process gives this test a clean provider without resetting SDK internals.
    code = '''
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, InMemoryLogRecordExporter
from app.telemetry import log_event, operation_span

spans = InMemorySpanExporter()
tracer = TracerProvider(shutdown_on_exit=False)
tracer.add_span_processor(SimpleSpanProcessor(spans))
trace.set_tracer_provider(tracer)
logs = InMemoryLogRecordExporter()
logger_provider = LoggerProvider(shutdown_on_exit=False)
logger_provider.add_log_record_processor(SimpleLogRecordProcessor(logs))
logger = logging.getLogger('unshaken.telemetry')
logger.setLevel(logging.INFO)
logger.addHandler(LoggingHandler(logger_provider=logger_provider))
with operation_span('lookup'):
    log_event('operation.completed', operation='lookup', outcome='success')
    log_event('secret personal note', operation='lookup', outcome='success')
record = logs.get_finished_logs()[0].log_record
assert len(logs.get_finished_logs()) == 1
assert record.body == 'operation.completed'
assert record.trace_id == spans.get_finished_spans()[0].context.trace_id
assert record.trace_id != 0
assert record.attributes['operation'] == 'lookup'
assert 'exception.message' not in record.attributes
logger_provider.shutdown()
tracer.shutdown()
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
