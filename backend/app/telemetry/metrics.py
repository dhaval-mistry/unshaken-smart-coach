"""Record a small set of safe, bounded operation metrics."""

import math
from opentelemetry import metrics
from .logging import safe_http_attributes, safe_labels


def record_operation(operation: str, outcome: str, duration_seconds: float) -> None:
    """Increment a counter and record a duration in seconds."""
    if not isinstance(duration_seconds, (int, float)) or not math.isfinite(duration_seconds) or duration_seconds < 0:
        return
    try:
        meter = metrics.get_meter("unshaken.telemetry")
        labels = safe_labels(operation, outcome)
        # The SDK reuses instruments with the same name and unit. Fixed labels
        # avoid creating a new time series for each user or request.
        meter.create_counter("unshaken.operation.count", unit="1").add(1, labels)
        meter.create_histogram("unshaken.operation.duration", unit="s").record(duration_seconds, labels)
    except Exception:
        pass


def record_http_request(
    route: str,
    method: str,
    status_code: int,
    duration_seconds: float,
    failure_category: str,
) -> None:
    """Record bounded foundation-route request counts and duration in seconds."""
    if (
        not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds < 0
    ):
        return
    try:
        meter = metrics.get_meter("unshaken.telemetry")
        attributes = safe_http_attributes(
            route, method, status_code, failure_category
        )
        meter.create_counter(
            "unshaken.http.server.request.count", unit="1"
        ).add(1, attributes)
        meter.create_histogram(
            "unshaken.http.server.request.duration", unit="s"
        ).record(duration_seconds, attributes)
    except Exception:
        pass  # Instrumentation must not change the HTTP result.
