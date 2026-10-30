# Local observability setup

Status: **PLANNED, NOT RUNNABLE YET**. Root Compose currently defines PostgreSQL
only. This guide describes the setup to implement from the approved local
[observability design](../architecture/observability.md). It does not install
or configure the stack today.

## What the tools do

- Grafana: one place to explore dashboards, logs and traces.
- Prometheus: numbers such as request count and response time.
- Loki: structured application logs.
- Tempo: connected steps showing where an operation spent time.
- OpenTelemetry Collector: receives and routes those signals.

All five are intended to run as Docker containers. Contributors should not
need to install each component directly on their computer or create a paid
cloud account for this local setup.

## Prerequisites available today

1. Follow the existing [Docker installation guide](docker.md).
2. Use the repository root and the existing private `.env` convention. If `.env`
   already exists, do not overwrite it with `.env.example`.
3. Review the architecture proposal. No observability environment variables or
   passwords have been added to the current template by this task.

## Planned startup after implementation

The following commands are **proposed, not currently working commands**. Run
them only after the service definitions and configurations have been added and
the implementing PR replaces this notice with verified instructions:

```text
docker compose --profile observability up -d otel-collector prometheus loki tempo grafana
docker compose --profile observability ps
docker compose --profile observability logs --tail 100 otel-collector prometheus loki tempo grafana
```

Use the existing root Compose project; do not start a second PostgreSQL service.
The optional stack must be usable with synthetic telemetry before a backend
exists. Starting containers alone does not provide application telemetry.

## Planned access and connections

| Client | Proposed destination |
|---|---|
| Browser | Grafana at `http://localhost:3000` |
| Backend on your computer | Collector OTLP HTTP at `http://localhost:4318` |
| Backend in the Compose network | Collector OTLP HTTP at `http://otel-collector:4318` |
| Grafana containers | Internal Prometheus, Loki, and Tempo service URLs |

The Collector base endpoint is protocol-specific: SDKs may append `/v1/traces`,
`/v1/metrics`, or `/v1/logs` for OTLP HTTP. The implementation must document the
selected SDK settings, protocol and full-path behavior rather than blindly
reusing an endpoint for OTLP gRPC.

Grafana credentials will come from private local configuration, with placeholders
only in `.env.example`. Do not assume a checked-in default password. Data sources
and reviewed dashboards should be provisioned automatically, so every developer
does not have to configure three connections by hand.

## Verification required before this guide is called runnable

- The chosen image versions and readiness checks work on the supported machine.
- Grafana data sources connect successfully over the Compose network.
- Synthetic metrics, logs and traces reach their respective stores through the
  Collector, and a log's trace ID opens the matching trace.
- A future backend exports real instrumented operations through the shared
  telemetry package; synthetic traffic is clearly identified.
- Stopping/restarting the stack preserves its intended local data and does not
  stop, recreate, migrate, or modify the PostgreSQL database.
- Sensitive fields are absent, queues/resource usage are bounded, and retention
  settings actually remove old data as designed.

## Planned stop command

After implementation, stop only these services to preserve database isolation:

```text
docker compose --profile observability stop grafana tempo loki prometheus otel-collector
```

Do not use `docker compose down -v` as routine troubleshooting; it can delete
the project's database volume as well as telemetry data. Data deletion requires
a separate, explicitly approved operation targeting exact disposable volumes.

## Troubleshooting checklist for the implemented stack

- Port already occupied: inspect the conflicting local service and the documented
  port override; do not stop an unrelated application without approval.
- No telemetry: distinguish missing instrumentation, unhealthy Collector,
  wrong endpoint/protocol, and failed storage connections.
- A container's `localhost` points to itself; use Compose service names between
  containers and published loopback ports from the host.
- Grafana connects but shows no data: check time range, service name, synthetic
  traffic generation, and whether queries match provisioned metrics/labels.
- Collector logs show dropped data: check queues, memory limits and store
  availability; do not log raw payloads or secrets to debug the problem.

Record exact commands and results in the implementation PR. No startup,
readiness, ingestion, retention or browser checks have been run for this draft.
