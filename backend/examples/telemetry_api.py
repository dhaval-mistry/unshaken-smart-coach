"""A local FastAPI demonstration of shared telemetry, not a product API."""

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.telemetry import initialize, log_event, operation_span, record_operation, shutdown
from app.telemetry.tracing import mark_error


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize once when the server starts and flush when it stops."""
    # Lifespan runs once per server process, rather than once per HTTP request.
    # Keeping exporter setup here avoids duplicate background workers.
    initialize(service="unshaken-demo")
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Local telemetry demonstration", lifespan=lifespan)


@app.get("/demo/operation")
def demo_operation(fail: bool = False):
    """Return a synthetic success or controlled failure with a correlated span."""
    start = perf_counter()
    with operation_span("demo") as span:
        outcome = "error" if fail else "success"
        if fail:
            mark_error(span)
        log_event("operation.failed" if fail else "operation.completed", operation="demo", outcome=outcome)
        record_operation("demo", outcome, perf_counter() - start)
    return JSONResponse({"status": outcome, "example": "synthetic"}, status_code=503 if fail else 200)
