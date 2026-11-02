# Telemetry examples

These small examples use `app.telemetry` and send synthetic data through the
local observability stack. They do not implement product APIs or connect to a
database. The database example simulates a read; no SQL or credentials are used.

From `backend/`, install dependencies and run the script twice:

```powershell
uv sync --locked
uv run python -m examples.telemetry_script
uv run python -m examples.telemetry_script --fail
```

The second command deliberately returns exit code 1. The script waits at most
three seconds for telemetry shutdown; a failure to export can drop signals but
does not turn a successful simulated operation into a failure.

In a separate terminal from `backend/`, start the temporary demonstration API:

```powershell
uv run uvicorn examples.telemetry_api:app --host 127.0.0.1 --port 18080
```

In another PowerShell terminal, call both outcomes:

```powershell
Invoke-WebRequest http://127.0.0.1:18080/demo/operation
Invoke-WebRequest 'http://127.0.0.1:18080/demo/operation?fail=true' -SkipHttpErrorCheck
```

The second call intentionally returns HTTP 503. `-SkipHttpErrorCheck` requires
PowerShell 7; in Windows PowerShell, use a browser or expect the HTTP error.
Stop the temporary API with Ctrl+C. It initializes the shared package once in
its lifespan and shuts it down on exit.

In Grafana Explore, choose **Loki** and search for either caller:

```logql
{service_name="unshaken-script"} |= "operation."
{service_name="unshaken-demo"} |= "operation."
```

Expand a log entry to see its trace ID and use the configured Tempo link. To
inspect metrics, choose **Mimir** and query:

```promql
unshaken_operation_count_total{operation="database"}
unshaken_operation_count_total{operation="demo"}
unshaken_operation_duration_seconds_count
```

The `outcome` label distinguishes success and error. The duration histogram is
measured in seconds. A trace is stored in Tempo; its ID is attached to the log
as structured metadata. If Alloy is unavailable, the examples still return the
same operation result, but telemetry may be dropped. See the
[setup guide](../../docs/setup/observability.md) for the local restart limitation.

Run the helper and example tests from `backend/`:

```powershell
uv run pytest tests/telemetry -q
```

To check both callers through the existing stack without interrupting services:

```powershell
uv run python scripts/verify_telemetry.py
```

The check needs the private Grafana credentials in the root `.env`. It looks
for fresh logs, matching traces and both metric outcomes through Grafana. It
opens no HTTP listening port, creates no Docker groups and does not access
PostgreSQL. This is normal-delivery evidence, not an outage or retention test.
