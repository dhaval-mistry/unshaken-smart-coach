"""Shared, opt-in telemetry for API processes and standalone scripts."""

from .setup import initialize, shutdown
from .logging import log_event
from .metrics import record_operation
from .tracing import operation_span

__all__ = ["initialize", "shutdown", "log_event", "record_operation", "operation_span"]
