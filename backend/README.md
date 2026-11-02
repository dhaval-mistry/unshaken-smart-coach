# Backend

The local database foundation now uses Python 3.12, uv, SQLAlchemy Core,
Psycopg 3, and Alembic. There is no FastAPI application or application API yet.

- `app/db/schema.py`: the 13-table metadata.
- `app/db/config.py`: existing private root DATABASE_URL settings.
- `app/db/cli.py`: nonsecret target/revision preview and confirmed upgrade.
- `app/db/operations.py`: small transactional capture/completion/version-lock primitives; not APIs or authentication.
- `migrations/`: frozen schema/guard SQL and separate versioned master seeds.
- `tests/`: real PostgreSQL 17 integration checks; test targets must have disposable names.

Follow [backend setup](../docs/setup/backend.md) and the
[database design](../docs/database/design.md). Future shared Python telemetry
belongs in `app/telemetry/` under its own story; no separate exporter setup
was added here. Keep one uv project for database and later API/telemetry work.
