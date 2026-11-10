"""Shared JSON error responses for routes and routing failures."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import REQUEST_ID_HEADER

# Fixed, safe messages. Never include the URL, method, or anything the caller sent.
HTTP_ERRORS = {
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "This method is not allowed for this resource."),
}


class ErrorDetail(BaseModel):
    """Safe public fields, without submitted input or exception details."""

    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """Shared envelope produced by the application's error handlers.

    Used for OpenAPI documentation; `error_response()` builds the same shape
    at runtime.
    """

    error: ErrorDetail


# OpenAPI metadata only. Runtime headers come from the middleware and from
# error_response(), including for unexpected-exception responses.
SHARED_RESPONSE_HEADERS = {
    "X-Request-ID": {
        "description": "Server-generated UUID; matches error.request_id on errors.",
        "schema": {"type": "string", "format": "uuid"},
    },
    "Cache-Control": {
        "description": "Responses must not be cached.",
        "schema": {"type": "string", "enum": ["no-store"]},
    },
}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the shared error envelope with the request's ID in body and header.

    The ID normally comes from the request-ID middleware via `request.state`.
    A new UUID is generated only as a fallback, if an error happens before
    that middleware ran, so every error still carries a matching ID.

    Headers are set here rather than left to the middleware because an
    unexpected exception is turned into a 500 by Starlette's outer error
    middleware, after our middleware has already been exited without
    reaching its header step.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    response_headers["Cache-Control"] = "no-store"
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    return JSONResponse(body, status_code=status_code, headers=response_headers)


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Turn routing errors such as 404 and 405 into the shared format.

    Starlette raises these for unknown paths and wrong methods. For 405 it puts
    the supported methods in `exc.headers` as `Allow`, which is passed through.
    Any other status falls back to a generic `http_error` code.
    """
    code, message = HTTP_ERRORS.get(
        exc.status_code, ("http_error", "The request could not be completed.")
    )
    return error_response(request, exc.status_code, code, message, exc.headers)


async def invalid_request(request: Request, _exc: RequestValidationError) -> JSONResponse:
    """Reject unsupported input without echoing anything the caller sent.

    FastAPI's default 422 includes the submitted values, so the validation
    details in `_exc` are intentionally ignored.
    """
    return error_response(
        request, 422, "invalid_request", "The request contains unsupported input."
    )


async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    """Hide unexpected failures behind a safe 500 response.

    Exception text can contain SQL, paths, hosts or credentials, so it is never
    returned. The full traceback still appears in the server log, where the
    request ID can be used to find it.
    """
    return error_response(request, 500, "internal_error", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    """Attach the shared error handlers to the application."""
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(Exception, internal_error)
