"""Operational health routes that never depend on PostgreSQL or providers."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import reject_unexpected_input
from app.api.errors import SHARED_RESPONSE_HEADERS, ErrorResponse

router = APIRouter(
    tags=["health"],
    prefix="/health",
    dependencies=[Depends(reject_unexpected_input)],
)


class LiveResponse(BaseModel):
    """Liveness only confirms that this process can answer."""

    status: Literal["alive"]


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
