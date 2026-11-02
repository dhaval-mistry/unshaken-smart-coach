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
Grafana, Alloy, Mimir, Loki and Tempo setup. It is not runnable until the stack
is implemented; see its linked architecture design for remaining decisions.

Before coding, follow the [developer reading path](../README.md) and review the
relevant designs in the [architecture index](../architecture/README.md).

The backend guide distinguishes current prerequisites from commands that will
become available when the FastAPI application is scaffolded. Frontend setup
will be added when frontend development begins.
