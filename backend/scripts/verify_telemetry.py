"""Send synthetic examples and verify normal delivery; never interrupt services."""

import os
from pathlib import Path
import subprocess
import sys
import time

from dotenv import dotenv_values
import httpx

BACKEND = Path(__file__).resolve().parents[1]


def run_examples() -> None:
    """Run callers in separate processes so each owns its SDK lifecycle."""
    commands = [
        (["-m", "examples.telemetry_script"], 0),
        (["-m", "examples.telemetry_script", "--fail"], 1),
        (["-c", """
from fastapi.testclient import TestClient
from examples.telemetry_api import app
# TestClient runs the application lifespan without opening a listening port.
with TestClient(app) as client:
    assert client.get('/demo/operation').status_code == 200
    assert client.get('/demo/operation?fail=true').status_code == 503
"""], 0),
    ]
    for arguments, expected in commands:
        result = subprocess.run(
            [sys.executable, *arguments], cwd=BACKEND,
            capture_output=True, text=True, timeout=15,
        )
        # Child output may include SDK diagnostics. Report a safe summary only.
        if result.returncode != expected:
            raise RuntimeError("A synthetic caller returned an unexpected result.")
    print("API and mocked script: success and controlled failure verified.")


def delivered(client: httpx.Client, start_ns: int) -> bool:
    """Query the stores through Grafana, matching each fresh log to its trace."""
    for service, operation in (("unshaken-script", "database"), ("unshaken-demo", "demo")):
        logs = client.get("/api/datasources/proxy/uid/loki/loki/api/v1/query_range", params={
            "query": f'{{service_name="{service}"}} |= "operation."',
            "start": str(start_ns), "end": str(time.time_ns()), "limit": 100,
        })
        logs.raise_for_status()
        trace_ids = set()
        outcomes = set()
        for stream in logs.json().get("data", {}).get("result", []):
            for entry in stream.get("values", []):
                # Loki can flatten structured metadata into the query's stream
                # fields. That response shape does not make it an index label.
                metadata = entry[2] if len(entry) > 2 else {}
                trace_id = metadata.get("trace_id", stream.get("stream", {}).get("trace_id"))
                if trace_id:
                    trace_ids.add(trace_id)
                outcomes.add(metadata.get("outcome", stream.get("stream", {}).get("outcome")))
        if not trace_ids or not {"success", "error"}.issubset(outcomes):
            return False
        for trace_id in trace_ids:
            response = client.get(f"/api/datasources/proxy/uid/tempo/api/traces/{trace_id}")
            if response.status_code == 404:
                return False  # A batch may reach Loki before Tempo; poll within the deadline.
            response.raise_for_status()
        for metric in ("unshaken_operation_count_total", "unshaken_operation_duration_seconds_count"):
            # Alloy's Prometheus conversion maps service.name to the job label.
            selector = f'{metric}{{job="{service}",operation="{operation}"}}'
            # An instant query's response time is not the sample's write time.
            # timestamp() excludes stale samples from an earlier demonstration.
            response = client.get("/api/datasources/proxy/uid/mimir/api/v1/query", params={
                "query": f'{selector} and (timestamp({selector}) >= {start_ns / 1e9})',
            })
            response.raise_for_status()
            results = response.json().get("data", {}).get("result", [])
            if not {"success", "error"}.issubset({row["metric"].get("outcome") for row in results}):
                return False
    return True


def main() -> int:
    """Check the local stack with private credentials and a bounded polling window."""
    settings = {**dotenv_values(BACKEND.parent / ".env"), **os.environ}
    username = settings.get("GRAFANA_ADMIN_USER")
    password = settings.get("GRAFANA_ADMIN_PASSWORD")
    if not username or not password:
        print("Set private Grafana credentials in the root .env before verification.")
        return 1
    try:
        port = int(settings.get("GRAFANA_PORT", "3000"))
        start_ns = time.time_ns()
        run_examples()
        # Basic credentials stay in memory. Only the loopback Grafana endpoint
        # is queried; no connection is made to PostgreSQL or vendor APIs.
        with httpx.Client(base_url=f"http://127.0.0.1:{port}",
                          auth=(username, password), timeout=5, trust_env=False) as client:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if delivered(client, start_ns):
                    print("Both callers: fresh logs, matching traces, counters and histograms found through Grafana.")
                    return 0
                time.sleep(2)
        print("Signals were not all found within 45 seconds. Check local service readiness.")
    except Exception:
        # HTTP failures can embed URLs or request headers; do not dump them.
        print("Verification failed. Inspect private settings and service readiness locally.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
