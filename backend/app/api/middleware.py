"""Shared HTTP behavior applied to every response."""

from uuid import uuid4

from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"


async def request_context(request: Request, call_next):
    """Give every request a server-generated ID and disable client caching."""
    request_id = str(uuid4())
    request.state.request_id = request_id

    response = await call_next(request)

    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers["Cache-Control"] = "no-store"
    return response