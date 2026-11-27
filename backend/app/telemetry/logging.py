"""Emit structured, allowlisted application events without user data."""

from uuid import UUID

from .setup import LOGGER

EVENTS = {
    "operation.started",
    "operation.completed",
    "operation.failed",
    "http.request.completed",
    "database_readiness.state_changed",
}
OPERATIONS = {"database", "lookup", "request", "script", "demo"}
OUTCOMES = {"started", "success", "error"}
AUTH_ROUTES = {
    f"/api/v1/auth/{provider}/{action}"
    for provider in ("google", "apple")
    for action in ("start", "callback")
} | {
    "/api/v1/auth/session", "/api/v1/auth/onboarding", "/api/v1/auth/logout",
    "/api/v1/auth/identities/google/link", "/api/v1/auth/identities/apple/link",
    "/api/v1/auth/apple/notifications",
}
HTTP_ROUTES = {
    "/health/live",
    "/health/ready",
    "/api/v1/exercise-categories",
    "/api/v1/body-parts",
}
HTTP_ROUTES |= AUTH_ROUTES
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
FAILURE_CATEGORIES = {
    "authentication_required", "authentication_failed", "authentication_unavailable", "forbidden", "rate_limited",
    "none",
    "invalid_request",
    "not_found",
    "method_not_allowed",
    "database_unavailable",
    "reference_data_unavailable",
    "internal_error",
    "http_error",
    "other",
}
READINESS_STATES = {
    "ready",
    "database_unavailable",
    "reference_data_unavailable",
    "internal_error",
}


def safe_labels(operation: str, outcome: str) -> dict[str, str]:
    """Map unknown values to bounded labels rather than exporting user input."""
    return {"operation": operation if operation in OPERATIONS else "other",
            "outcome": outcome if outcome in OUTCOMES else "other"}


def safe_http_attributes(
    route: str,
    method: str,
    status_code: int,
    failure_category: str,
) -> dict[str, str | int]:
    """Return bounded dimensions for one canonical foundation API route."""
    status = status_code if type(status_code) is int and 100 <= status_code <= 599 else 0
    return {
        "http.route": route if route in HTTP_ROUTES else "other",
        "http.request.method": method if method in HTTP_METHODS else "OTHER",
        "http.response.status_code": status,
        "failure.category": (
            failure_category if failure_category in FAILURE_CATEGORIES else "other"
        ),
    }


def safe_request_id(request_id: str) -> str | None:
    """Accept only a server-generated UUID-shaped correlation identifier."""
    try:
        return str(UUID(request_id))
    except (AttributeError, TypeError, ValueError):
        return None


def log_event(event: str, *, operation: str = "other", outcome: str = "other") -> None:
    """Log a known event; unknown text and unsupported fields are not exported."""
    if event not in EVENTS:
        return
    try:
        LOGGER.info(event, extra=safe_labels(operation, outcome))
    except Exception:
        pass  # A logging failure must not change the business operation.


def log_http_request(
    *,
    route: str,
    method: str,
    status_code: int,
    duration_seconds: float,
    failure_category: str,
    request_id: str,
) -> None:
    """Emit one safe lookup request event correlated with its active span."""
    attributes = safe_http_attributes(route, method, status_code, failure_category)
    correlation_id = safe_request_id(request_id)
    if attributes["http.route"] not in {
        "/api/v1/exercise-categories",
        "/api/v1/body-parts",
    } | AUTH_ROUTES:
        return
    if not isinstance(duration_seconds, (int, float)) or duration_seconds < 0:
        return
    try:
        LOGGER.info(
            "http.request.completed",
            extra={
                **attributes,
                "operation": "authentication" if route in AUTH_ROUTES else "lookup",
                "outcome": "success" if status_code < 400 else "error",
                "duration_seconds": float(duration_seconds),
                **({"request_id": correlation_id} if correlation_id else {}),
            },
        )
    except Exception:
        pass  # Logging must never change the lookup result.


def log_readiness_transition(state: str, request_id: str) -> None:
    """Log only a known readiness transition, with no request or database data."""
    if state not in READINESS_STATES:
        return
    correlation_id = safe_request_id(request_id)
    try:
        LOGGER.info(
            "database_readiness.state_changed",
            extra={
                "readiness_state": state,
                **({"request_id": correlation_id} if correlation_id else {}),
            },
        )
    except Exception:
        pass
