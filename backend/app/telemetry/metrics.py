"""Record a small set of safe, bounded operation metrics."""

import math
from opentelemetry import metrics
from .logging import safe_labels


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
