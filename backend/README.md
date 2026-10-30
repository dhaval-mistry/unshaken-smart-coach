# Backend

The FastAPI application, database migrations, provider integrations, and AI
coach workflow will live here. Backend unit and integration tests will live in
`backend/tests/` when the application is scaffolded.

Read the [system overview](../docs/architecture/overview.md) before scaffolding
packages. The starting layout places shared Python telemetry in
`backend/app/telemetry/`, reused by FastAPI and backend Python scripts.
There is no working application or telemetry package here yet.
