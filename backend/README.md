# Backend

The FastAPI application, database migrations, provider integrations, and AI
coach workflow will live here. Backend unit and integration tests will live in
`backend/tests/` when the application is scaffolded.

## Database migrations

`pyproject.toml`, `uv.lock` and `migrations/` hold the database tooling. Run
`uv sync`, then follow [docs/database/migrations.md](../docs/database/migrations.md).
Tests: `uv run pytest`.
