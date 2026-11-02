# Local setup

Follow these guides in order:

1. [Install Docker](docker.md).
2. [Start PostgreSQL in Docker](postgresql.md).
3. [Get individual ExerciseDB API access](exercisedb.md).
4. [Prepare the backend development environment](backend.md).
5. Optionally, [install pgAdmin and connect to PostgreSQL](pgadmin.md).

Team members using Codex or Claude Code can also configure the
[reusable development agents](development-agents.md).

The [observability setup guide](observability.md) describes the proposed local
Grafana, Alloy, Mimir, Loki, and Tempo revision while preserving OpenTelemetry.
The design records the earlier Collector/Prometheus approval. The revision
needs approval, implementation, and testing before it is runnable.

Before coding, follow the [developer reading path](../README.md). Setup guides
explain how to run tools; product rules and design choices live in the
[architecture index](../architecture/README.md) and linked documents.

The backend guide distinguishes current prerequisites from commands that will
become available when the FastAPI application is scaffolded. Frontend setup
will be added when frontend development begins.
