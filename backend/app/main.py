"""FastAPI application entry point for the UNShaken backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.telemetry import initialize, shutdown
from app.api.health import router as health_router
from app.api.middleware import request_context
from app.api.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start shared telemetry once at startup and stop it once at shutdown."""
    initialize(service="unshaken-backend")
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="UNShaken Smart Coach API", lifespan=lifespan)

app.middleware("http")(request_context)

register_error_handlers(app)

app.include_router(health_router)