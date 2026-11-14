"""FastAPI application entry point for the UNShaken backend."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.middleware import request_context
from app.telemetry import initialize, shutdown

API_DESCRIPTION = """
Every response carries a server-generated `X-Request-ID` (UUID) and
`Cache-Control: no-store`. Errors use one JSON envelope:
`{"error": {"code": "...", "message": "...", "request_id": "..."}}`, where
`request_id` matches the `X-Request-ID` header.

Application-wide routing errors, which no single operation lists:

- Unknown paths return `404` with code `not_found`. Paths are matched exactly;
  a trailing slash such as `/health/live/` is an unknown path, not a redirect.
- Unsupported methods return `405` with code `method_not_allowed` and an
  `Allow` header listing the supported methods (for `/health/live`: `GET`).
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Own the shared telemetry lifecycle and the readiness database pool.

    Telemetry is started once here, not at import time or per request, so a
    process never installs duplicate exporters. The shared helpers decide
    failure behavior: `initialize()` returns False instead of raising when
    telemetry is disabled or exporter setup fails, and exports then fail in
    background workers without changing HTTP responses. `shutdown()` waits at
    most a few seconds to flush and reports, rather than raises, a failed
    flush. `finally` makes shutdown run even if serving stops with an error.

    The database pool is created lazily by the first readiness check, so it is
    only disposed here if this process ever loaded it.
    """
    initialize(service="unshaken-backend")
    try:
        yield
    finally:
        # The pool module loads on the first database-backed request, so a
        # process that never needed PostgreSQL has nothing to dispose.
        pool = sys.modules.get("app.db.pool")
        if pool is not None:
            pool.dispose_engine()
        shutdown()


app = FastAPI(
    title="UNShaken Smart Coach API",
    description=API_DESCRIPTION,
    lifespan=lifespan,
    # Without this, Starlette answers /health/live/ with an empty 307 redirect
    # that is not JSON. Disabling it sends slash variants to the shared JSON
    # 404 handler, keeping /health/live as the single canonical path.
    redirect_slashes=False,
)

# Registered once for the whole app, so routing errors (404/405) get the same
# request ID and no-cache headers as route responses.
app.middleware("http")(request_context)
register_error_handlers(app)
app.include_router(health_router)
