"""Create safe operation spans shared by API handlers and scripts."""

from contextlib import contextmanager
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from .logging import OPERATIONS


def mark_error(span) -> None:
    """Mark a failure without copying exception text or private input."""
    try:
        span.set_status(Status(StatusCode.ERROR))
        span.set_attribute("error.type", "operation_failed")
    except Exception:
        pass  # Instrumentation must never change the operation's result.


@contextmanager
def operation_span(operation: str):
    """Start a span without automatically exporting exception text or input."""
    name = operation if operation in OPERATIONS else "other"
    tracer = trace.get_tracer("unshaken.telemetry")
    # The active span is stored in OpenTelemetry's execution context. Logging
    # reads that context automatically, so callers do not pass trace IDs around.
    # Exception text is excluded because it can contain SQL or private inputs.
    with tracer.start_as_current_span(f"unshaken.{name}", record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception:
            mark_error(span)
            raise
