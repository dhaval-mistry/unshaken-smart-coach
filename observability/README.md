# Observability

Future Grafana Alloy, Mimir, Loki, Tempo, and Grafana configuration will live
here as those capabilities are introduced. OpenTelemetry remains the shared
application instrumentation; Alloy collects and forwards its signals.

Keep runnable configurations here and human instructions under `docs/`:

- [Architecture design](../docs/architecture/observability.md)
- [Planned local setup](../docs/setup/observability.md)

No component configuration exists yet. The proposed services will use an
optional profile in the existing root Compose file, preserving PostgreSQL.
