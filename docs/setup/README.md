# Local setup

Follow these guides in order:

1. [Install Docker](docker.md).
2. [Start PostgreSQL in Docker](postgresql.md).
3. [Get individual ExerciseDB API access](exercisedb.md).
4. [Prepare the backend development environment](backend.md).
5. Optionally, [install pgAdmin and connect to PostgreSQL](pgadmin.md).

Team members using Codex or Claude Code can also configure the
[reusable development agents](development-agents.md).

The [observability setup guide](observability.md) describes the optional local
Grafana, Alloy, Mimir, Loki and Tempo stack and its verification limits.

The FastAPI backend runs either on the host or as a hardened local Compose
service. See [backend setup](backend.md#run-the-api-in-docker) for image,
startup, health, telemetry, and explicit migration commands.

Before coding, follow the [developer reading path](../README.md) and review the
relevant designs in the [architecture index](../architecture/README.md).

The backend guide documents both runtime choices and the shared database tools.
Frontend setup will be added when frontend development begins.
