"""Create safe operation spans shared by API handlers and scripts."""

from contextlib import contextmanager
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from .logging import HTTP_ROUTES, OPERATIONS, safe_request_id


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


@contextmanager
def http_request_span(route: str, method: str, request_id: str):
    """Trace one public lookup with only canonical route and safe correlation data."""
    safe_route = route if route in HTTP_ROUTES else "other"
    safe_method = method if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER"
    tracer = trace.get_tracer("unshaken.telemetry")
    with tracer.start_as_current_span(
        f"HTTP {safe_method} {safe_route}",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("http.route", safe_route)
        span.set_attribute("http.request.method", safe_method)
        correlation_id = safe_request_id(request_id)
        if correlation_id:
            span.set_attribute("request.id", correlation_id)
        try:
            yield span
        except Exception:
            mark_error(span)
            raise


@contextmanager
def database_read_span(table_name: str):
    """Trace one bounded lookup read without exporting SQL or parameters."""
    safe_table = (
        table_name
        if table_name in {"exercise_categories", "body_parts"}
        else "other"
    )
    tracer = trace.get_tracer("unshaken.telemetry")
    with tracer.start_as_current_span(
        "database.read",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("db.system.name", "postgresql")
        span.set_attribute("db.operation.name", "select")
        span.set_attribute("db.collection.name", safe_table)
        try:
            yield span
        except Exception:
            mark_error(span)
            raise
