"""Shared request checks for routes that accept no input."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError


async def reject_unexpected_input(request: Request) -> None:
    """Return 422 for any query parameter or request body."""
    if request.query_params or await request.body():
        raise RequestValidationError([])