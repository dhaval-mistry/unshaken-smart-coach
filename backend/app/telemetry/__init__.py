"""Shared, opt-in telemetry for API processes and standalone scripts."""

from .setup import initialize, shutdown
from .logging import log_event, log_http_request, log_readiness_transition
from .metrics import record_http_request, record_operation
from .tracing import database_read_span, http_request_span, operation_span

__all__ = [
    "initialize",
    "shutdown",
    "log_event",
    "log_http_request",
    "log_readiness_transition",
    "record_operation",
    "record_http_request",
    "operation_span",
    "http_request_span",
    "database_read_span",
]
