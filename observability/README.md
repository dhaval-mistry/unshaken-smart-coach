# Observability

Grafana Alloy, Mimir, Loki, Tempo, and Grafana configuration lives here.
OpenTelemetry remains the shared
application instrumentation; Alloy collects and forwards its signals.

Keep runnable configurations here and human instructions under `docs/`:

- [Architecture design](../docs/architecture/observability.md)
- [Local setup and verification limits](../docs/setup/observability.md)

The services use an optional profile in the root Compose file, preserving PostgreSQL.
