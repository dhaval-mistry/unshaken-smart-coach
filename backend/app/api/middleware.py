"""Shared HTTP behavior applied to every response."""

from uuid import uuid4

from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"


async def request_context(request: Request, call_next):
    """Give every request a server-generated ID and disable client caching.

    The ID exists only to correlate one request across responses and logs,
    for example when a user reports an error. It is never authorization or
    identity, so any `X-Request-ID` the caller sends is deliberately not read:
    a fresh UUID is always generated here.

    The ID is stored in `request.state` so error handlers can put the same
    value in the error body. If the route raises an unexpected exception,
    `call_next` does not return and the header lines below are skipped; the
    500 handler sets these headers itself (see `app.api.errors`).
    """
    request_id = str(uuid4())
    request.state.request_id = request_id

    response = await call_next(request)

    response.headers[REQUEST_ID_HEADER] = request_id
    # Health results and lookup choices must be fresh, so nothing is cached.
    response.headers["Cache-Control"] = "no-store"
    return response
