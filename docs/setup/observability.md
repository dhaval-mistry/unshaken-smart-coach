# Local observability setup

The optional Docker Compose profile runs Alloy, Mimir, Loki, Tempo and Grafana.
It is independent of PostgreSQL. See the [architecture and approved decisions](../architecture/observability.md).
The shared Python OpenTelemetry package and synthetic API/script examples are
implemented. Product API endpoints remain separate work.

## Before starting

Start Docker Desktop and use the repository root. Follow the [Docker guide](docker.md)
if needed. Keep your existing private `.env`; copy `.env.example` only if it
does not already exist. Add your own private Grafana credentials to `.env`:

```dotenv
GRAFANA_ADMIN_USER=choose-your-local-user
GRAFANA_ADMIN_PASSWORD=choose-your-own-local-password
```

These are examples, not credentials. Never commit `.env` or put a real password
in `.env.example`. Grafana refuses to start when either value is empty. Grafana
initializes its admin account in its own volume on first startup; changing these
variables later does not automatically change an existing account's password.

By default Grafana uses `127.0.0.1:3000` and Alloy receives OTLP HTTP on
`127.0.0.1:4318`. If a port is in use, set `GRAFANA_PORT` or `ALLOY_OTLP_PORT`
in your private `.env`. Other service and diagnostic ports remain internal.

## Start and check

From the repository root, start only the five observability services:

```powershell
docker compose --profile observability up -d --no-deps alloy mimir loki tempo grafana
docker compose --profile observability ps
./scripts/check-observability.ps1
```

The PowerShell check uses Grafana's bundled curl to reach each service over the
internal network. Store initialization can take time; retry the check if a store
is still starting. Readiness checks do not prove that signals reached storage.

Open `http://127.0.0.1:3000` (or your configured port) and sign in using your
private credentials. Mimir, Loki and Tempo data sources are provisioned. Grafana
uses the Prometheus data-source type to query Mimir; no Prometheus server runs.

Applications on the host send OTLP HTTP to `http://127.0.0.1:4318`;
containers in this Compose network use `http://alloy:4318`. The exporter adds
the `/v1/logs`, `/v1/metrics` or `/v1/traces` path. Alloy routes logs to Loki,
metrics through remote write to Mimir, and traces to Tempo. No Docker socket or
container-log collection is configured. Never send secrets or personal data.

To stop or restart the stack without touching PostgreSQL or deleting volumes:

```powershell
docker compose --profile observability stop alloy mimir loki tempo grafana
docker compose --profile observability start alloy mimir loki tempo grafana
```

Do not use `docker compose down -v` as a normal setup or troubleshooting step.
Separate named volumes hold each store, Grafana and Alloy's remote-write state.
Retention is configured for three days of logs and metrics and 24 hours of
traces. Cleanup is asynchronous, and retention is not a disk quota.

## Verification and limits

### Normal local verification

Run from `backend/` after the existing stack is ready:

```powershell
uv sync --locked
uv run pytest tests/telemetry -q
uv run python scripts/verify_telemetry.py
```

The last command runs synthetic API requests without a listening server and a
mocked database script. It checks success/error logs, their matching Tempo
traces, and fresh Mimir counter/histogram samples through Grafana. It never
stops services, creates Docker groups or connects to PostgreSQL or ExerciseDB.
It reads Grafana credentials privately from the root `.env` or environment.

Verified working tree: `feature/local-observability-stack`, 2026-11-02. These
changes are uncommitted; the results do not identify a new published commit.

| Command | Result |
|---|---|
| `uv run pytest tests/telemetry -q` | 12 passed; one Starlette/httpx deprecation warning |
| `uv run python scripts/verify_telemetry.py` | Both callers returned expected success/error outcomes; fresh logs, matching traces, counters and histograms found through Grafana |
| `./scripts/check-observability.ps1` from root | All six readiness checks passed |
| `python -m unittest discover -s tests -v` from root | 8 existing repository tests passed |
| `git diff --check` | Passed |

The locked Python packages include OpenTelemetry SDK/exporter 1.45.2,
FastAPI 0.162.0, Uvicorn 0.54.0 and httpx 0.28.1 on Python 3.12. The dependency
warning concerns TestClient's httpx integration; it did not fail the tests.

Mimir exposes the counter as `unshaken_operation_count_total` and the duration
histogram as `unshaken_operation_duration_seconds` (`_count`, `_sum`, `_bucket`).
Durations are seconds. The `job` label identifies the service, while `operation`
and `outcome` use fixed known values. Request, trace and user IDs are not metric
labels. For example:

```promql
unshaken_operation_count_total{job="unshaken-demo",outcome="success"}
unshaken_operation_duration_seconds_count{job="unshaken-script"}
```

Live log records were matched to Tempo traces by their trace IDs. SDK in-memory
tests also checked this correlation and dropped unknown free-text events.
These checks do not guarantee that arbitrary future code cannot emit sensitive
data; callers must use the documented safe helpers.

A read-only memory snapshot after verification showed about 44 MiB Alloy,
39 MiB Mimir, 76 MiB Grafana, 77 MiB Loki and 178 MiB Tempo. These observations
are not laptop minimum requirements, peak-load measurements or disk limits.

For the owner's reduced local scope, #9's package and #10's examples are
implemented and verified. #11's normal-delivery guide and checks are complete;
the additional checks listed under **Accepted local scope and deferred checks**
remain deferred, rather than being reported as passed. No GitHub issue state
has been changed by this implementation.

The implementation was exercised on a separate disposable Compose project with
alternate loopback ports and synthetic data. All five services started; the
readiness script reached each one. Grafana queried a synthetic log, metric and
trace from the three provisioned data sources; all three were retrievable again
after a service restart. PostgreSQL was not stopped or migrated. The Loki index
label check showed only the synthetic service name, not its trace ID.

Alloy removes a few common sensitive attribute names as a second safeguard;
this does not sanitize arbitrary log bodies, resource fields or unknown keys.
The shared library limits event names, operations and outcomes to safe known
values. Callers must also avoid adding sensitive span attributes or console logs.
The synthetic API and simulated database-script examples are documented in
[backend/examples](../../backend/examples/README.md). Both produce success and
controlled-failure signals, and their results were unchanged while Alloy was
unavailable. Earlier one-service-at-a-time checks recorded correct caller
results and new-signal recovery for Alloy, Mimir, Loki and Tempo. They are
historical evidence, not a required setup step or a promise of buffered delivery.

## Accepted local scope and deferred checks

The owner accepted the combined Mimir-outage/Alloy-restart metric gap for local
development and requested no further outage tests or temporary Docker groups.
Retention deletion tests were stopped; their temporary containers, networks and
volumes were removed. The normal project remains `unshaken-smart-coach`.

Grafana's log-to-trace **UI click**, actual retention cleanup and measured disk
bounds remain unverified. The matching log and trace were retrieved by ID, but
that does not prove the UI link. The configured three-day log/metric and 24-hour
trace policies remain in place. These checks are deferred; they have not passed.

A disposable test that stopped Mimir and restarted Alloy did not recover
its synthetic buffered metric. A second test on the local stack confirmed two samples were
pending in Alloy before its restart; the synthetic metric was not found in Mimir
after recovery, even when querying its original timestamp and waiting longer.
The metric was confirmed in the persistent WAL before restart. In the pinned
Alloy version, the [WAL watcher source](https://github.com/grafana/prometheus/blob/a2b6722387bf/tsdb/wlog/watcher.go)
sets its start timestamp to the current time and forwards only later samples;
this matches the observed gap. Alloy v1.20.1's
[watcher source](https://github.com/grafana/prometheus/blob/6ac45be9754c/tsdb/wlog/watcher.go)
has the same timestamp filter. Grafana tracks
[replay work](https://github.com/grafana/alloy/issues/5808).
Do not rely on the buffer to protect all metrics across this combined outage
and restart. This is accepted for the local version; it affects monitoring
metrics, not PostgreSQL workout records. Production needs a separate durability,
redundancy and load design. More containers alone do not provide those guarantees.
A healthy service is not proof of signal delivery. No outage or retention-test
commands are part of the current setup instructions.

Pinned images: Alloy v1.8.3, Mimir 2.15.0, Loki 3.4.3, Tempo 2.7.2 and Grafana
11.6.0. Mimir started with one process, classic ingestion, replication factor
one and filesystem storage. No Kafka or MinIO was needed. A small synthetic
run showed roughly 42 MiB Alloy, 37 MiB Mimir, 37 MiB Loki, 110 MiB Tempo and
76 MiB Grafana at one moment; this is not a minimum system requirement.

For troubleshooting, run `docker compose --profile observability ps` and inspect
service logs locally. Review logs before sharing them. Check the root `.env`,
loopback port conflicts and Docker Desktop resource limits. A Grafana login or
empty dashboard does not prove that an application is sending data.
