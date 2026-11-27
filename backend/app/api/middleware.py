"""Shared HTTP behavior applied to every response."""

import time
from uuid import uuid4

from fastapi import Request
from opentelemetry.trace import Status, StatusCode

from app.telemetry import (
    http_request_span,
    log_http_request,
    record_http_request,
)
from app.telemetry.logging import FAILURE_CATEGORIES, HTTP_ROUTES

REQUEST_ID_HEADER = "X-Request-ID"
LOOKUP_ROUTES = {
    "/api/v1/exercise-categories",
    "/api/v1/body-parts",
}


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

    route = request.url.path if request.url.path in HTTP_ROUTES else None
    started = time.perf_counter()
    status_code = 500
    failure_category = "internal_error"
    span_context = (
        http_request_span(route, request.method, request_id)
        if route in LOOKUP_ROUTES
        else None
    )
    if span_context is None:
        response = await call_next(request)
    else:
        with span_context as span:
            try:
                response = await call_next(request)
            except Exception:
                status_code = 500
                # The outer 500 handler has not run while this middleware
                # unwinds, so request.state cannot supply its category yet.
                failure_category = "internal_error"
                duration = time.perf_counter() - started
                _record_request(
                    route,
                    request.method,
                    status_code,
                    duration,
                    failure_category,
                )
                span.set_attribute("http.response.status_code", status_code)
                span.set_attribute("failure.category", failure_category)
                log_http_request(
                    route=route,
                    method=request.method,
                    status_code=status_code,
                    duration_seconds=duration,
                    failure_category=failure_category,
                    request_id=request_id,
                )
                raise
            status_code = response.status_code
            failure_category = _failure_category(request, status_code)
            duration = time.perf_counter() - started
            _record_request(
                route,
                request.method,
                status_code,
                duration,
                failure_category,
            )
            span.set_attribute("http.response.status_code", status_code)
            span.set_attribute("failure.category", failure_category)
            if status_code >= 500:
                span.set_attribute("error.type", failure_category)
                span.set_status(Status(StatusCode.ERROR))
            log_http_request(
                route=route,
                method=request.method,
                status_code=status_code,
                duration_seconds=duration,
                failure_category=failure_category,
                request_id=request_id,
            )

    if route and route not in LOOKUP_ROUTES:
        status_code = response.status_code
        failure_category = _failure_category(request, status_code)
        _record_request(
            route,
            request.method,
            status_code,
            time.perf_counter() - started,
            failure_category,
        )

    response.headers[REQUEST_ID_HEADER] = request_id
    # Health results and lookup choices must be fresh, so nothing is cached.
    response.headers["Cache-Control"] = "no-store"
    return response


def _failure_category(request: Request, status_code: int) -> str:
    """Read only a known error category set by the shared response builder."""
    category = getattr(request.state, "telemetry_failure_category", None)
    if category in FAILURE_CATEGORIES and category != "none":
        return category
    if status_code < 400:
        return "none"
    return "other"


def _record_request(
    route: str,
    method: str,
    status_code: int,
    duration_seconds: float,
    failure_category: str,
) -> None:
    """Record metrics only for fixed foundation routes."""
    record_http_request(
        route, method, status_code, duration_seconds, failure_category
    )
