"""Verify foundation API signals in Grafana using an existing disposable DB."""

import json
import math
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
METRIC_NAMES = (
    "unshaken_http_server_request_count_total",
    "unshaken_http_server_request_duration_seconds_count",
)
EXPECTED_INCREMENTS = {
    ("/health/live", "200", "none"): 3,
    ("/health/ready", "200", "none"): 2,
    ("/api/v1/exercise-categories", "200", "none"): 1,
    ("/api/v1/body-parts", "422", "invalid_request"): 1,
}


def _attributes(metadata: object) -> dict:
    """Normalize safe structured log attributes from Loki's response shapes."""
    if isinstance(metadata, dict):
        result = dict(metadata)
    elif isinstance(metadata, list):
        result = {
            str(item[0]): item[1]
            for item in metadata
            if isinstance(item, (list, tuple)) and len(item) == 2
        }
    elif isinstance(metadata, str):
        try:
            decoded = json.loads(metadata)
        except (TypeError, ValueError):
            return {}
        return _attributes(decoded)
    else:
        return {}
    for key in ("attributes", "structured_metadata", "structuredMetadata"):
        nested = result.get(key)
        if isinstance(nested, dict):
            result.update(nested)
    return result


def _field(attributes: dict, *names: str):
    """Read one known field across Loki's preserved/normalized key spellings."""
    for name in names:
        if name in attributes:
            return attributes[name]
    return None


def _proxy(
    client: httpx.Client,
    datasource: str,
    path: str,
    **parameters,
) -> httpx.Response:
    """Query one provisioned data source through the local Grafana proxy."""
    response = client.get(
        f"/api/datasources/proxy/uid/{datasource}/{path}",
        params=parameters,
    )
    response.raise_for_status()
    return response


def _query_request_logs(
    client: httpx.Client,
    start_ns: int,
) -> list[dict]:
    """Fetch fresh safe API request logs without displaying payloads."""
    response = _proxy(
        client,
        "loki",
        "loki/api/v1/query_range",
        query='{service_name="unshaken-backend"} |= "http.request.completed"',
        start=str(start_ns),
        end=str(time.time_ns()),
        limit=500,
    )
    records = []
    for stream in response.json().get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for entry in stream.get("values", []):
            metadata = _attributes(entry[2] if len(entry) > 2 else {})
            line = entry[1] if len(entry) > 1 else ""
            if not metadata:
                metadata = _attributes(labels)
            if not metadata:
                metadata = _attributes(line)
            records.append(
                {
                    "labels": labels,
                    "metadata": metadata,
                    "line": line,
                    "shape": (
                        len(entry),
                        type(entry[2]).__name__ if len(entry) > 2 else "missing",
                        sorted(metadata),
                        sorted(labels),
                        line.startswith("http.request.completed"),
                        len(line),
                    ),
                }
            )
    return records


def _query_metric(
    client: httpx.Client,
    metric_name: str,
    start_ns: int,
) -> list[dict]:
    """Return fresh Mimir samples for one service metric."""
    selector = f'{metric_name}{{job="unshaken-backend"}}'
    response = _proxy(
        client,
        "mimir",
        "api/v1/query",
        query=f"{selector} and (timestamp({selector}) >= {start_ns / 1e9})",
    )
    return response.json().get("data", {}).get("result", [])


def _metric_counts(series: list[dict]) -> dict[tuple, float]:
    """Keep expected exact series identities; ignore unrelated historical routes."""
    counts = {}
    for row in series:
        labels = row.get("metric", {})
        expected_key = (
            _field(labels, "http.route", "http_route"),
            str(_field(labels, "http.response.status_code", "http_response_status_code")),
            _field(labels, "failure.category", "failure_category"),
        )
        if (
            expected_key not in EXPECTED_INCREMENTS
            or _field(labels, "http.request.method", "http_request_method") != "GET"
        ):
            continue
        identity = tuple(sorted(labels.items()))
        value = float(row["value"][1])
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError("A request count was not a finite nonnegative integer.")
        if identity in counts:
            raise ValueError("Duplicate metric series were returned.")
        counts[identity] = value
    return counts


def _metrics_increased(before: list[dict], after: list[dict]) -> bool:
    """Require observed increases for every synthetic request's bounded labels.

    A new series starts at zero for this comparison. A disappearing or reset
    series is inconclusive: fail closed and rerun against a stable API process
    rather than treating a counter reset as evidence of delivered requests.
    """
    baseline = _metric_counts(before)
    current = _metric_counts(after)
    if any(key not in current or current[key] < value for key, value in baseline.items()):
        return False
    increments = dict.fromkeys(EXPECTED_INCREMENTS, 0.0)
    for identity, value in current.items():
        labels = dict(identity)
        if _field(labels, "http.request.method", "http_request_method") != "GET":
            continue
        key = (
            _field(labels, "http.route", "http_route"),
            str(_field(labels, "http.response.status_code", "http_response_status_code")),
            _field(labels, "failure.category", "failure_category"),
        )
        if key in increments:
            increments[key] += value - baseline.get(identity, 0.0)
    return all(increments[key] >= count for key, count in EXPECTED_INCREMENTS.items())


def _normalize_trace_id(value: object) -> str:
    """Normalize Grafana's optional `0x` prefix without exposing the ID."""
    return str(value or "").lower().removeprefix("0x")


def _validate_test_database() -> sa.engine.URL:
    """Refuse the live-check runner unless it names an explicit disposable DB."""
    if os.environ.get("USC_API_TELEMETRY_DISPOSABLE") != "1":
        raise ValueError("Explicit disposable-database confirmation is required.")
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise ValueError("TEST_DATABASE_URL is required for API telemetry verification.")
    url = make_url(value)
    if not url.database or not url.database.startswith("unshaken_foundation_test_"):
        raise ValueError("API telemetry verification refuses non-test database names.")
    return url


def _verify_database_contents(url: sa.engine.URL) -> dict[str, list[dict]]:
    """Read seed rows only from the verified disposable target."""
    engine = sa.create_engine(url, hide_parameters=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            current_database = connection.exec_driver_sql(
                "SELECT current_database()"
            ).scalar_one()
            if current_database != url.database:
                raise ValueError("Connected database does not match the test target.")
            return {
                table: [
                    dict(row)
                    for row in connection.execute(
                        sa.text(
                            f"SELECT id, name, sort_order FROM {table} "
                            "WHERE is_active IS TRUE ORDER BY sort_order, id"
                        )
                    ).mappings()
                ]
                for table in ("exercise_categories", "body_parts")
            }
    finally:
        engine.dispose()


def main() -> int:
    """Exercise safe API paths and verify correlated signals through Grafana."""
    stage = "checking the disposable database target"
    try:
        test_url = _validate_test_database()
        stage = "reading synthetic seed rows from the disposable database"
        expected = _verify_database_contents(test_url)
        stage = "loading private Grafana settings"
        settings = {**dotenv_values(ROOT / ".env"), **os.environ}
        username = settings.get("GRAFANA_ADMIN_USER")
        password = settings.get("GRAFANA_ADMIN_PASSWORD")
        if not username or not password:
            raise ValueError("Private Grafana credentials are required.")
        api_base = settings.get(
            "API_TELEMETRY_BASE_URL",
            "http://127.0.0.1:8000",
        )
        grafana_port = int(settings.get("GRAFANA_PORT", "3000"))
        stage = "capturing Mimir counts before synthetic requests"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{grafana_port}",
            auth=(username, password), timeout=8, trust_env=False,
        ) as grafana:
            # No freshness restriction on the baseline: a refreshed old series
            # must not be mistaken for metrics caused by this run's requests.
            baseline = {
                name: _query_metric(grafana, name, 0) for name in METRIC_NAMES
            }
        start_ns = time.time_ns()
        marker = f"synthetic-{uuid4().hex}"
        stage = "calling real health and lookup endpoints"
        with httpx.Client(
            base_url=api_base,
            timeout=5,
            trust_env=False,
        ) as api:
            liveness = [api.get("/health/live") for _ in range(3)]
            readiness = [api.get("/health/ready") for _ in range(2)]
            success = api.get("/api/v1/exercise-categories")
            failure = api.get(
                "/api/v1/body-parts",
                params={"verification_marker": marker},
            )
        stage = "checking health endpoint responses"
        if any(response.status_code != 200 for response in liveness + readiness):
            raise ValueError("A health endpoint returned an unexpected status.")
        stage = "checking controlled lookup outcomes"
        if success.status_code != 200 or failure.status_code != 422:
            raise ValueError("The lookup API did not return expected synthetic outcomes.")
        stage = "comparing API rows with the disposable database"
        if success.json().get("items") != expected["exercise_categories"]:
            raise ValueError("The successful API result did not match disposable DB rows.")
        request_ids = {
            "success": UUID(success.headers["x-request-id"]),
            "failure": UUID(failure.headers["x-request-id"]),
        }
        liveness_ids = [UUID(response.headers["x-request-id"]) for response in liveness]
        readiness_ids = [UUID(response.headers["x-request-id"]) for response in readiness]
        stage = "checking liveness bodies"
        if not all(response.json().get("status") == "alive" for response in liveness):
            raise ValueError("Liveness returned an unexpected response.")

        stage = "querying local Grafana for API logs and metrics"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{grafana_port}",
            auth=(username, password),
            timeout=8,
            trust_env=False,
        ) as grafana:
            deadline = time.monotonic() + 45
            counter = []
            duration = []
            stage = "waiting for request-specific Loki logs and fresh Mimir samples"
            while time.monotonic() < deadline:
                logs = _query_request_logs(grafana, start_ns)
                by_request = {}
                for record in logs:
                    attrs = record["metadata"]
                    request_id = _field(attrs, "request_id", "request.id")
                    if request_id:
                        by_request[str(request_id)] = record
                counter = _query_metric(
                    grafana,
                    "unshaken_http_server_request_count_total",
                    start_ns,
                )
                duration = _query_metric(
                    grafana,
                    "unshaken_http_server_request_duration_seconds_count",
                    start_ns,
                )
                if (
                    all(str(request_id) in by_request for request_id in request_ids.values())
                    and _metrics_increased(baseline[METRIC_NAMES[0]], counter)
                    and _metrics_increased(baseline[METRIC_NAMES[1]], duration)
                ):
                    break
                time.sleep(2)
            else:
                fields = sorted(
                    {
                        key
                        for record in logs
                        for key in record["metadata"]
                    }
                )
                services = sorted(
                    {
                        str(record["labels"].get("service_name", "missing"))
                        for record in logs
                    }
                )
                raise RuntimeError(
                    "Request-specific logs or required metric increases not observed; "
                    f"record_count={len(logs)}, metadata_keys={fields}, "
                    f"services={services}, entry_shapes="
                    f"{[record['shape'] for record in logs]}."
                )

            marker_text = marker
            stage = "checking safe request fields and log/trace correlation"
            correlated_trace_ids = {}
            for kind, request_id in request_ids.items():
                record = by_request[str(request_id)]
                attrs = record["metadata"]
                expected_route = (
                    "/api/v1/exercise-categories"
                    if kind == "success"
                    else "/api/v1/body-parts"
                )
                expected_status = 200 if kind == "success" else 422
                trace_id = _normalize_trace_id(
                    _field(attrs, "trace_id", "trace.id")
                    or record["labels"].get("trace_id")
                )
                if (
                    _field(attrs, "http.route", "http_route") != expected_route
                    or int(_field(attrs, "http.response.status_code", "http_response_status_code") or 0)
                    != expected_status
                    or _field(attrs, "failure.category", "failure_category")
                    != ("none" if kind == "success" else "invalid_request")
                    or not trace_id
                ):
                    raise ValueError("A safe API log field or trace correlation was missing.")
                correlated_trace_ids[kind] = trace_id
                if marker_text in str(record):
                    raise ValueError("A raw synthetic query marker appeared in a Loki log.")

            if correlated_trace_ids["success"] == correlated_trace_ids["failure"]:
                raise ValueError("Distinct API requests unexpectedly shared a trace ID.")
            for kind, trace_id in correlated_trace_ids.items():
                stage = "checking Tempo traces and the real database-read span"
                trace_response = _proxy(
                    grafana,
                    "tempo",
                    f"api/traces/{trace_id}",
                )
                trace_text = str(trace_response.json())
                if marker_text in trace_text:
                    raise ValueError("Tempo trace contained the raw synthetic marker.")
                if kind == "success" and (
                    "database.read" not in trace_text
                    or "exercise_categories" not in trace_text
                ):
                    names = []
                    def collect_span_names(value: object) -> None:
                        """Collect only fixed span names for safe verification diagnostics."""
                        if isinstance(value, dict):
                            if isinstance(value.get("name"), str):
                                names.append(value["name"])
                            for child in value.values():
                                collect_span_names(child)
                        elif isinstance(value, list):
                            for child in value:
                                collect_span_names(child)
                    collect_span_names(trace_response.json())
                    raise RuntimeError(
                        "Successful trace lacks DB span; "
                        f"span_names={sorted(set(names))}."
                    )

            stage = "checking converted Mimir metric names and bounded labels"
            for series in (counter, duration):
                labels = [row.get("metric", {}) for row in series]
                found = {
                    (
                        _field(item, "http.route", "http_route"),
                        str(_field(item, "http.response.status_code", "http_response_status_code")),
                    )
                    for item in labels
                }
                if not {
                    ("/api/v1/exercise-categories", "200"),
                    ("/api/v1/body-parts", "422"),
                    ("/health/live", "200"),
                    ("/health/ready", "200"),
                }.issubset(found):
                    raise ValueError("Fresh request metrics or bounded labels were missing in Mimir.")
            if any(
                key in row.get("metric", {})
                for series in (counter, duration)
                for row in series
                for key in ("request_id", "trace_id", "user_id")
            ):
                raise ValueError("An identifier was found in a metric label.")

            indexed_series = _proxy(
                grafana,
                "loki",
                "loki/api/v1/series",
                **{
                    "match[]": '{service_name="unshaken-backend"}',
                    "start": str(start_ns),
                    "end": str(time.time_ns()),
                },
            ).json().get("data", [])
            indexed_keys = {
                key
                for series in indexed_series
                for key in series
            }
            if indexed_keys.intersection(
                {"request_id", "trace_id", "span_id", "user_id"}
            ):
                raise ValueError("An identifier was found in Loki index labels.")

            stage = "checking readiness-transition logs"
            readiness_logs = _proxy(
                grafana,
                "loki",
                "loki/api/v1/query_range",
                query='{service_name="unshaken-backend"} |= "database_readiness.state_changed"',
                start=str(start_ns),
                end=str(time.time_ns()),
                limit=100,
            ).json().get("data", {}).get("result", [])
            transition_records = []
            for stream in readiness_logs:
                stream_fields = _attributes(stream.get("stream", {}))
                for entry in stream.get("values", []):
                    attributes = _attributes(entry[2] if len(entry) > 2 else {})
                    if not attributes:
                        attributes = stream_fields
                    if _field(attributes, "request_id", "request.id") == str(
                        readiness_ids[0]
                    ):
                        transition_records.append(attributes)
            if len(transition_records) != 1:
                raise ValueError("Readiness polls did not produce exactly one state transition.")

        print(
            "PASS: real API success/controlled validation failure, safe Loki logs, "
            "correlated Tempo traces, database-read span, Mimir metric increases and one "
            "readiness transition were verified."
        )
        print(
            "Mimir metrics: unshaken_http_server_request_count_total and "
            "unshaken_http_server_request_duration_seconds_count; duration unit "
            "is seconds (verified against the SDK histogram)."
        )
        print(
            f"Health polls checked: liveness={len(liveness_ids)}, "
            f"readiness={len(readiness_ids)}; request and trace IDs were not metric labels."
        )
        return 0
    except Exception as exc:
        # HTTP/database exceptions may contain local URLs or credentials.
        detail = f" {exc}" if type(exc) is RuntimeError else ""
        print(
            f"Verification failed while {stage} ({type(exc).__name__}).{detail} "
            "Check local readiness and private settings; no secret values were printed."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
