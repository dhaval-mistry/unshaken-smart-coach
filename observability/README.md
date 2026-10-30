# Observability

OpenTelemetry collector configuration and future Grafana, Prometheus, Loki,
and Tempo configuration will live here as those capabilities are introduced.

Keep runnable configurations here and human instructions under `docs/`:

- [Approved local design](../docs/architecture/observability.md)
- [Planned local setup](../docs/setup/observability.md)

No component configuration exists yet. The approved local direction uses an
optional profile in the existing root Compose file, preserving PostgreSQL.

Shared Python telemetry belongs in `backend/app/telemetry/`, not this folder.
See the [system overview](../docs/architecture/overview.md) for code ownership.
