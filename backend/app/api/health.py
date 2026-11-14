"""Operational health routes: liveness and bounded database readiness."""

import asyncio
import logging
import time
from importlib import import_module
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies import reject_unexpected_input
from app.api.errors import SHARED_RESPONSE_HEADERS, ErrorResponse, error_response
from app.telemetry import log_event

router = APIRouter(
    tags=["health"],
    prefix="/health",
    dependencies=[Depends(reject_unexpected_input)],
)

LOGGER = logging.getLogger("unshaken.api.health")

# The contract is a three-second total; the margin lets the response itself
# leave within it after a check is abandoned at the budget.
READINESS_BUDGET_SECONDS = 2.9

READINESS_FAILURES = {
    "database_unavailable": "The database is temporarily unavailable. Try again shortly.",
    "reference_data_unavailable": "Required reference data is not available.",
}

_last_readiness_state = "ready"

LIVE_DESCRIPTION = """
**What it is:** a liveness check for the backend process.

**What it is used for:** process monitors and participants use it to confirm
that the API is running and can answer HTTP requests, for example after
starting the server. It makes no database, provider, AI or telemetry call, so
it keeps returning `200` while PostgreSQL or the observability stack is down.
It does not prove the backend can serve data; use `GET /health/ready` for that.
"""

READY_DESCRIPTION = """
**What it is:** a readiness check for serving exercise data.

**What it is used for:** participants and readiness monitors use it to confirm
that the backend can actually read PostgreSQL. It performs short, read-only
reads of the two lookup tables used by the New exercise form
(`exercise_categories` and `body_parts`) and requires at least one active row
in each. The whole check, including waiting for a connection, finishes within
three seconds.

- `200` means both lists can be read.
- `503 database_unavailable` means PostgreSQL could not be reached or read in
  time.
- `503 reference_data_unavailable` means a lookup table is missing or has no
  active rows.

It never creates tables, runs migrations or repairs data, and it does not
verify every table or the migration version. Telemetry and external providers
do not affect the result.
"""


class LiveResponse(BaseModel):
    """Liveness only confirms that this process can answer."""

    status: Literal["alive"]


class ReadyResponse(BaseModel):
    """Readiness confirms both exercise-form reference lists can be read."""

    status: Literal["ready"]


def _error_doc(description: str, *examples: tuple[str, str]) -> dict:
    """Describe one shared-envelope error status for OpenAPI, with examples."""
    return {
        "model": ErrorResponse,
        "description": description,
        "headers": SHARED_RESPONSE_HEADERS,
        "content": {
            "application/json": {
                "examples": {
                    code: {
                        "value": {
                            "error": {
                                "code": code,
                                "message": message,
                                "request_id": "64a96af7-f5cc-49a9-918e-d5cdedcdd65b",
                            }
                        }
                    }
                    for code, message in examples
                }
            }
        },
    }


READINESS_RESPONSES = {
    200: {
        "description": "Both reference lists have active rows.",
        "headers": SHARED_RESPONSE_HEADERS,
    },
    422: _error_doc(
        "Unsupported query parameters or request body (error code: invalid_request).",
        ("invalid_request", "The request contains unsupported input."),
    ),
    500: _error_doc(
        "Unexpected failure with a safe public message (error code: internal_error).",
        ("internal_error", "An unexpected error occurred."),
    ),
    503: _error_doc(
        "PostgreSQL could not be read in time, or reference data is missing.",
        *READINESS_FAILURES.items(),
    ),
}


def _record_readiness(state: str, request_id: str, exception_type: str | None = None) -> None:
    """Log only state changes, using fixed fields, so polling an outage is quiet."""
    global _last_readiness_state
    if state == _last_readiness_state:
        return
    _last_readiness_state = state
    if state == "ready":
        log_event("operation.completed", operation="database", outcome="success")
        LOGGER.info("readiness.recovered request_id=%s", request_id)
        return
    log_event("operation.failed", operation="database", outcome="error")
    # The class name is safe; str(exc) could contain SQL or connection details.
    LOGGER.warning(
        "readiness.failed code=%s request_id=%s exception_type=%s",
        state,
        request_id,
        exception_type or "none",
    )


async def _check_database() -> str | None:
    """Load database code on first use, then run the bounded check."""
    deadline = time.monotonic() + READINESS_BUDGET_SECONDS
    # Imported here, off the event loop, so startup and liveness never load
    # database code and the first request's import counts against the budget.
    readiness = await asyncio.to_thread(import_module, "app.db.readiness")
    return await readiness.check_readiness(deadline)


@router.get(
    "/live",
    summary="Check that the API process is running",
    description=LIVE_DESCRIPTION,
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
    summary="Check that the API can read its PostgreSQL reference data",
    description=READY_DESCRIPTION,
    response_model=ReadyResponse,
    responses=READINESS_RESPONSES,
)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    """Report whether both reference lists can be read within the deadline.

    Only state changes are logged, with fixed fields and the exception class
    name, never exception text. See app.db.readiness for how the deadline is
    enforced against a blocking database driver.
    """
    request_id = request.state.request_id
    try:
        failure = await asyncio.wait_for(_check_database(), READINESS_BUDGET_SECONDS)
    except TimeoutError:
        failure = "database_unavailable"
    except Exception as exc:
        # Handled here because the framework's fallback re-raises to the server
        # log, and database exception text can contain SQL or connection details.
        _record_readiness("internal_error", request_id, type(exc).__name__)
        return error_response(request, 500, "internal_error", "An unexpected error occurred.")
    if failure is not None:
        _record_readiness(failure, request_id)
        return error_response(request, 503, failure, READINESS_FAILURES[failure])
    _record_readiness("ready", request_id)
    return ReadyResponse(status="ready")
