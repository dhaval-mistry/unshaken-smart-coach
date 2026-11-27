"""Operational health routes for liveness and bounded readiness."""

import threading
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies import reject_unexpected_input
from app.api.errors import SHARED_RESPONSE_HEADERS, ErrorResponse, error_response

_readiness_lock = threading.Lock()

router = APIRouter(
    tags=["health"],
    prefix="/health",
    dependencies=[Depends(reject_unexpected_input)],
)


class LiveResponse(BaseModel):
    """Liveness only confirms that this process can answer."""

    status: Literal["alive"]


class ReadyResponse(BaseModel):
    """Readiness confirms bounded reads of both required reference lists."""

    status: Literal["ready"]


def _get_database_readiness(app):
    """Create and reuse the process-scoped readiness resource on first use."""
    with _readiness_lock:
        resources = getattr(app.state, "database_readiness", None)
        if resources is None:
            from app.db.readiness import DatabaseReadiness

            resources = DatabaseReadiness.from_environment()
            app.state.database_readiness = resources
        return resources


def shutdown_database_readiness(app) -> bool:
    """Shut down a lazily created readiness resource, if one exists."""
    with _readiness_lock:
        resources = getattr(app.state, "database_readiness", None)
        app.state.database_readiness = None
    if resources is None:
        return True
    return resources.shutdown()


@router.get(
    "/live",
    # Exception handlers are invisible to OpenAPI, so the error responses this
    # route can produce are declared here. Routing errors (404/405) are
    # app-wide and documented in the API description in app.main.
    responses={
        200: {
            "description": "The process can answer HTTP requests.",
            "headers": SHARED_RESPONSE_HEADERS,
        },
        422: {
            "model": ErrorResponse,
            "description": (
                "Unsupported query parameters or request body "
                "(error code: invalid_request)."
            ),
            "headers": SHARED_RESPONSE_HEADERS,
        },
        500: {
            "model": ErrorResponse,
            "description": (
                "Unexpected failure with a safe public message "
                "(error code: internal_error)."
            ),
            "headers": SHARED_RESPONSE_HEADERS,
        },
    },
)
def live() -> LiveResponse:
    """Report process liveness without checking external dependencies.

    No database, provider, AI or telemetry call is made, so this keeps
    returning 200 while those are unavailable. Health probes are deliberately
    not logged or traced, per docs/api/foundation.md, to avoid noise.
    """
    return LiveResponse(status="alive")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={
        200: {
            "description": "Both active PostgreSQL reference lists are readable.",
            "headers": SHARED_RESPONSE_HEADERS,
        },
        422: {
            "model": ErrorResponse,
            "description": "Unsupported input (error code: invalid_request).",
            "headers": SHARED_RESPONSE_HEADERS,
        },
        503: {
            "model": ErrorResponse,
            "description": (
                "Database or required reference data is unavailable "
                "(error code: database_unavailable or reference_data_unavailable)."
            ),
            "headers": SHARED_RESPONSE_HEADERS,
        },
        500: {
            "model": ErrorResponse,
            "description": "Incompatible schema or unexpected application failure.",
            "headers": SHARED_RESPONSE_HEADERS,
        },
    },
)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    """Read both active lookup lists inside the shared three-second boundary."""
    resources = _get_database_readiness(request.app)
    result = await resources.check()
    request_id = request.state.request_id
    resources.record_state(result, request_id)
    from app.db.readiness import ReadinessState

    if result.state == ReadinessState.READY:
        return ReadyResponse(status="ready")
    if result.state == ReadinessState.DATABASE_UNAVAILABLE:
        return error_response(
            request,
            503,
            "database_unavailable",
            "The database is temporarily unavailable. Try again shortly.",
        )
    if result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE:
        return error_response(
            request,
            503,
            "reference_data_unavailable",
            "Required reference data is temporarily unavailable. Try again shortly.",
        )
    return error_response(
        request,
        500,
        "internal_error",
        "An unexpected error occurred.",
    )
