# Backend

The local database foundation now uses Python 3.12, uv, SQLAlchemy Core,
Psycopg 3, and Alembic. There is no FastAPI application or application API yet.

- `app/db/schema.py`: the 13-table metadata.
- `app/db/config.py`: existing private root DATABASE_URL settings.
- `app/db/cli.py`: nonsecret target/revision preview and confirmed upgrade.
- `app/db/operations.py`: small transactional capture/completion/version-lock primitives; not APIs or authentication.
- `migrations/`: frozen schema/guard SQL and separate versioned master seeds.
- `tests/`: database integration checks and shared telemetry unit tests.
- `app/telemetry/`: opt-in shared logs, metrics and spans for future API and script callers.
- `examples/`: [synthetic API and script examples](examples/README.md), with no database changes.

Follow [backend setup](../docs/setup/backend.md) and the
[database design](../docs/database/design.md). Reuse `app/telemetry/` for API
and script callers; do not configure store-specific exporters in business code.
Keep one uv project for database, API and telemetry work.
Review the [system overview](../docs/architecture/overview.md) before adding packages.

## Shared telemetry

Call `initialize()` once when a process starts and `shutdown()` when it exits.
Importing the package does not connect to Alloy. For a standalone script:

```python
from app.telemetry import initialize, log_event, operation_span, record_operation, shutdown

initialize(service="unshaken-script")
try:
    with operation_span("script"):
        log_event("operation.completed", operation="script", outcome="success")
        record_operation("script", "success", 0.12)  # Duration is in seconds.
finally:
    shutdown()
```

A future FastAPI application should call the same initialization and shutdown
functions once in its application lifespan and use the same helpers in handlers.
The API itself is not implemented here.

Supported event names are `operation.started`, `operation.completed` and
`operation.failed`. Supported operations are `database`, `lookup`, `request`,
`script`, and `demo`; outcomes are `started`, `success`, and `error`. Unknown
operations/outcomes become `other`; unknown event names are dropped. These
limits prevent personal input and IDs becoming metric labels. Do not put
credentials, personal details, SQL, raw requests, or exception messages in
span attributes or console logs. A span intentionally does not record exception
text automatically.

Set `OTEL_SDK_DISABLED=true` in the private root `.env` to disable exporters.
The default OTLP HTTP base is `http://127.0.0.1:4318`; use `http://alloy:4318`
inside the Compose network. The library appends `/v1/logs`, `/v1/metrics`, and
`/v1/traces` to the base. If `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`,
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`, or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
is set, its complete URL is used as-is. Never include credentials in an endpoint.

Exporters have a two-second network timeout. `shutdown()` waits at most three
seconds total and returns `False` if cleanup is still running or an SDK flush
reports failure; pending data may
be lost when the process exits. `initialize()` returns `False` if disabled or
invalid. After shutdown, start a new process rather than reinitializing global
providers. The existing local Alloy metric-replay limitation still applies.

For normal delivery verification, run `uv run python scripts/verify_telemetry.py`
from `backend/`. It runs only synthetic examples and reads Grafana; it does not
stop services, create Docker groups or access PostgreSQL. SDK flush completion
does not guarantee that a downstream store has persisted a signal.
