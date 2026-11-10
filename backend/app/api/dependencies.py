"""Shared request checks for routes that accept no input."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError


async def reject_unexpected_input(request: Request) -> None:
    """Return 422 for any query parameter or request body.

    FastAPI only validates parameters a route declares, and silently ignores
    anything else: `/health/live?foo=bar` would otherwise succeed. The design
    requires such input to be rejected, so this check runs before each route
    that accepts no input.

    It raises `RequestValidationError` with an empty error list on purpose.
    That reuses the shared `invalid_request` handler, which returns a fixed
    message and never echoes the submitted query or body back to the caller.
    """
    if request.query_params or await request.body():
        raise RequestValidationError([])
