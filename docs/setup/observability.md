# Local observability setup

Status: **PLANNED, NOT RUNNABLE YET**. Alloy collection and Mimir metrics
storage are approved, but the stack is not installed. Root Compose still defines
PostgreSQL only. This guide contains no claim that the future commands work.

Read the [design and approval record](../architecture/observability.md).
The earlier approved plan used a standalone Collector and Prometheus. The
approved direction keeps OpenTelemetry in application code and uses Alloy
for collection plus Mimir for metrics storage. Do not mix the two service lists.

## What will run

| Service | Purpose |
|---|---|
| Alloy | Receive application OpenTelemetry logs, metrics, and traces; forward them |
| Mimir | Store metrics; answer Grafana's PromQL queries |
| Loki | Store logs |
| Tempo | Store traces |
| Grafana | Explore all three stores |

These are proposed containers in the existing root Compose project's optional
`observability` profile. PostgreSQL stays independent. The approved local
Mimir variant is one process, classic ingestion, replication factor one, and
filesystem storage, with no Kafka or MinIO container. The selected image still
needs version-specific runtime verification; see the design's storage discussion.

## Prerequisites available today

1. Follow the existing [Docker guide](docker.md).
2. Use the repository root and existing private `.env` convention. Do not
   overwrite a personal `.env` with `.env.example`.
3. Review the approved design and update existing stories #7-#15
   through the separately requested Product Owner workflow.
4. During implementation, select fixed compatible images, writable data paths,
   and private Grafana credentials. Commit placeholders only. No observability
   configuration/settings were added by this documentation task.

A backend is not required to verify the stack using clearly labeled synthetic
signals. A healthy stack alone does not instrument an application.

## Planned startup after implementation

**Proposed and unverified. These commands do not work with current Compose.**
Use them only after implementation replaces this notice with tested instructions.

```text
docker compose --profile observability up -d alloy mimir loki tempo grafana
docker compose --profile observability ps
docker compose --profile observability logs --tail 100 alloy mimir loki tempo grafana
```

Start only the listed services. Do not recreate PostgreSQL, migrate it, or
reset a volume as a side effect. Review logs locally and redact secrets before
sharing them. Do not print expanded Compose/configuration as evidence.

## Planned access and signal destinations

| Client | Proposed destination |
|---|---|
| Browser | Grafana `http://127.0.0.1:3000` |
| Python process on host | Alloy OTLP HTTP base `http://127.0.0.1:4318` |
| Python process in Compose | Alloy OTLP HTTP base `http://alloy:4318` |
| Alloy metrics export | Mimir remote write `http://mimir:9009/api/v1/push` |
| Alloy log export | Loki native OTLP base `http://loki:3100/otlp` |
| Alloy trace export | Tempo OTLP HTTP base `http://tempo:4318` |
| Grafana Mimir data source | Prometheus type, base `http://mimir:9009/prometheus` |
| Grafana Loki data source | `http://loki:3100` |
| Grafana Tempo data source | `http://tempo:3200` |
| Alloy diagnostics inside Compose | `http://alloy:12345` |

Only Grafana 3000 and Alloy 4318 are proposed as host loopback bindings.
Mimir, Loki, Tempo, Alloy administration, and gRPC remain internal. A
container's localhost points to itself, not another service.

The shared Python package still exports all signals using OpenTelemetry.
Document the actual SDK protocol and base/per-signal endpoint settings:
HTTP paths are `/v1/logs`, `/v1/metrics`, and `/v1/traces`.
Do not send HTTP traffic to a gRPC port or append a signal path twice.
The complete routing and source references live in the
[design](../architecture/observability.md#components-and-signal-flow).

Provision all Grafana data sources and log-to-trace links automatically.
Use private Grafana credentials with anonymous access disabled. The proposed
stores are single-tenant inside a trusted local network; they are not secure
public services. Remote/shared use needs a separate access design.

## Application logs and container logs

The approved initial scope uses application logs sent through OpenTelemetry.
Console logging remains available locally, but Alloy must not also collect
those same entries through Docker.

The application-only setup needs no Docker socket or host-log mount.
Docker container-log collection is deferred. If later approved, document the exact
container allowlist, platform-specific daemon permissions, duplicate prevention,
read positions, and safe restart behavior before enabling it. A read-only
socket mount does not restrict Docker API actions.

## Verification before calling this guide runnable

Record selected versions, tested commit, exact commands, results, safe queries,
and limitations in the implementation PR, then replace planned instructions.

| Step | What must be demonstrated |
|---|---|
| Validate configuration | Version-specific config parsing and Compose wiring; no secrets printed |
| Check each service | Working probes for Grafana `/api/health`, Loki/Mimir/Tempo `/ready`, Alloy `/-/ready` and `/-/healthy` |
| Send synthetic data | A known counter/histogram, safe log event, and matching trace reach the stores |
| Query through Grafana | Metric is queried from Mimir, log from Loki, trace from Tempo; log opens the correct trace |
| Check failures | Stop Alloy or each store separately using disposable telemetry; application/script result remains correct and waits are bounded |
| Check recovery | New signals arrive after recovery; document buffered versus dropped data |
| Check storage | Restart services and verify intended store data/Alloy remote-write state; measure disk and memory use |
| Check retention | Three-day metrics/log and 24-hour trace policy; actual cleanup verified with disposable telemetry and documented delays |
| Check PostgreSQL isolation | Observability start/stop/restart leaves PostgreSQL running and data unchanged |
| Check real callers later | #10 verifies examples; #15 verifies actual lookup requests; separate live evidence from mocks |

Alloy readiness means its initial configuration loaded; it does not prove
signals reached storage. Probes must work with the chosen images; do not
assume they contain curl or a shell. Never treat an empty Grafana dashboard as
proof of either a broken stack or a working application.

## Planned stop command

**Proposed and unverified; available only after implementation:**

```text
docker compose --profile observability stop grafana tempo loki mimir alloy
```

This targets only observability. Stopping preserves volumes; deleting data is
a separate operation requiring approval for exact disposable targets. Do not
use `docker compose down -v` as routine setup or troubleshooting.

## Troubleshooting for the future implementation

- No metrics: inspect Alloy conversion/remote-write errors and Mimir readiness.
  Mimir is the store; there is no separate Prometheus server or old 8889 scrape
  endpoint in this proposal.
- Empty metric query: verify the Grafana Prometheus-type data source uses the
  Mimir `/prometheus` prefix and the actual converted metric name/time range.
- Logs rejected: check Loki structured metadata/schema support and the native
  `/otlp/v1/logs` destination.
- Missing traces: distinguish Tempo ingestion 4318 from its query port 3200.
- Duplicate logs: check whether the same application stream is exported by
  both its SDK and Docker log collection.
- Growing disk: inspect remote-write backlog, Mimir WAL/blocks/compactor,
  Loki/Tempo retention, and cleanup delays. Retention is not a hard disk quota.
- Store unavailable: inspect safe error counters and queue/drop behavior.
  Do not log raw telemetry payloads, credentials, or sensitive SQL to debug it.
- Grafana healthy but no data: check delivery and queries separately; verify
  synthetic service labels and log-to-trace data-source links.
- A selected Mimir image requires extra infrastructure: stop and revisit the
  design; do not silently add Kafka, object storage, or a cloud account.

No containers were started, probes run, telemetry delivered, or retention
measured by this design task. This guide remains planned.
