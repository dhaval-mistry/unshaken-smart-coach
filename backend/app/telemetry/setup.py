"""Initialize the shared OpenTelemetry providers once per process."""

import logging
import os
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urljoin, urlparse

from dotenv import dotenv_values
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_lock = Lock()
_providers = None
_finished = False
LOGGER = logging.getLogger("unshaken.telemetry")
ROOT = Path(__file__).resolve().parents[3]


def _setting(name: str, default: str = "") -> str:
    """Prefer the process environment over the existing private root .env."""
    return os.environ.get(name, dotenv_values(ROOT / ".env").get(name) or default)


def _endpoint(signal: str) -> str:
    """Use per-signal URLs as-is; append each path once to the base URL."""
    override = _setting(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    base = _setting("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    value = override or urljoin(base.rstrip("/") + "/", f"v1/{signal}")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid private OTLP endpoint")
    return value


def initialize(service: str = "unshaken-backend", enabled: bool | None = None) -> bool:
    """Install exporters once; return False when disabled or initialization fails."""
    global _providers
    with _lock:
        if _providers is not None:
            return True
        if _finished or (enabled is False) or (enabled is None and _setting("OTEL_SDK_DISABLED").lower() == "true"):
            return False
        # Service names are configuration, not user input or personal data.
        if service not in {"unshaken-backend", "unshaken-script", "unshaken-demo"}:
            return False
        try:
            endpoints = {signal: _endpoint(signal) for signal in ("logs", "metrics", "traces")}
            # Do not import arbitrary process/environment resource attributes:
            # they may contain private values or high-cardinality identifiers.
            resource = Resource({"service.name": service})
            traces = TracerProvider(resource=resource, shutdown_on_exit=False)
            traces.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoints["traces"], timeout=2)))
            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoints["metrics"], timeout=2), export_interval_millis=5000)
            meters = MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False)
            logs = LoggerProvider(resource=resource, shutdown_on_exit=False)
            logs.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoints["logs"], timeout=2)))
            handler = LoggingHandler(logger_provider=logs)
            LOGGER.addHandler(handler)
            LOGGER.setLevel(logging.INFO)
            trace.set_tracer_provider(traces)
            metrics.set_meter_provider(meters)
            _providers = (traces, meters, logs, handler)
            return True
        except Exception:
            # Telemetry configuration must not stop the caller or print secrets.
            return False


def shutdown(timeout_seconds: float = 3.0) -> bool:
    """Bound the caller's wait; return False if a flush fails or cleanup times out."""
    global _providers, _finished
    with _lock:
        if _providers is None:
            return True
        providers = _providers
        _providers = None
        _finished = True
        LOGGER.removeHandler(providers[3])

    # Finishing cleanup is different from delivering every pending signal. Keep
    # the providers' flush results so callers are not given a false success.
    flushed = [True]

    def stop():
        for provider in providers[:3]:
            try:
                if not provider.force_flush(timeout_millis=1000):
                    flushed[0] = False
            except Exception:
                flushed[0] = False
            try:
                # Still release resources when force_flush reports a failure.
                provider.shutdown()
            except Exception:
                flushed[0] = False

    # SDK shutdown methods do not all accept a deadline. A daemon worker limits
    # how long a short-lived script waits even during a network failure.
    worker = Thread(target=stop, daemon=True, name="telemetry-shutdown")
    worker.start()
    worker.join(max(0.0, min(timeout_seconds, 3.0)))
    return not worker.is_alive() and flushed[0]
