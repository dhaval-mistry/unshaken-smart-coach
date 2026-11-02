# Observability

Future collection, storage, and Grafana configuration will live here. The
current proposal uses Alloy, Mimir, Loki, Tempo, and Grafana while keeping
OpenTelemetry in application code.

Keep runnable configurations here and human instructions under `docs/`:

- [Proposed revision and earlier approval record](../docs/architecture/observability.md)
- [Planned local setup](../docs/setup/observability.md)

No component configuration exists yet. The optional root Compose profile and
PostgreSQL isolation keep their earlier approval. The Alloy/Mimir changes need
owner review before implementation; do not build both old and new pipelines.

Shared Python telemetry belongs in `backend/app/telemetry/`, not this folder.
See the [system overview](../docs/architecture/overview.md) for code ownership.
