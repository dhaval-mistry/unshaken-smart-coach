"""Emit structured, allowlisted application events without user data."""

from .setup import LOGGER

EVENTS = {"operation.started", "operation.completed", "operation.failed"}
OPERATIONS = {"database", "lookup", "request", "script", "demo"}
OUTCOMES = {"started", "success", "error"}


def safe_labels(operation: str, outcome: str) -> dict[str, str]:
    """Map unknown values to bounded labels rather than exporting user input."""
    return {"operation": operation if operation in OPERATIONS else "other",
            "outcome": outcome if outcome in OUTCOMES else "other"}


def log_event(event: str, *, operation: str = "other", outcome: str = "other") -> None:
    """Log a known event; unknown text and unsupported fields are not exported."""
    if event not in EVENTS:
        return
    try:
        LOGGER.info(event, extra=safe_labels(operation, outcome))
    except Exception:
        pass  # A logging failure must not change the business operation.
