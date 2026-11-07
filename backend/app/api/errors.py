"""Shared JSON error responses for routes and routing failures."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

from app.api.middleware import REQUEST_ID_HEADER

# Fixed, safe messages. Never include the URL, method, or anything the caller sent.
HTTP_ERRORS = {
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "This method is not allowed for this resource."),
}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the shared error envelope with the request's ID in body and header."""
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    response_headers["Cache-Control"] = "no-store"
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    return JSONResponse(body, status_code=status_code, headers=response_headers)


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Turn routing errors such as 404 and 405 into the shared format."""
    code, message = HTTP_ERRORS.get(
        exc.status_code, ("http_error", "The request could not be completed.")
    )
    return error_response(request, exc.status_code, code, message, exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    """Attach the shared error handlers to the application."""
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(Exception, internal_error)

async def invalid_request(request: Request, _exc: RequestValidationError) -> JSONResponse:
    """Reject unsupported input without echoing anything the caller sent."""
    return error_response(
        request, 422, "invalid_request", "The request contains unsupported input."
    )

async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    """Hide unexpected failures behind a safe 500 response."""
    return error_response(
        request, 500, "internal_error", "An unexpected error occurred."
    )