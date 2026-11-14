"""Live readiness checks; requires a disposable PostgreSQL 17 test server.

Needs the migrated TEST_DATABASE_URL target used by tests/test_database.py.
Failure scenarios run in separate scratch databases on that same server, so the
migrated database is only ever read.
"""

import os
import subprocess
import sys
import time
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app import main
from app.api import health
from app.db import pool, readiness
from app.db.config import database_engine, database_url

LOOKUP_TABLE = "CREATE TABLE {name} (id SMALLINT PRIMARY KEY, is_active BOOLEAN NOT NULL)"
SECRET_FRAGMENTS = ("SELECT", "postgresql", "exercise_categories", "foundation_test", "127.0.0.1")


@pytest.fixture(scope="module")
def migrated_url():
    """Return the disposable migrated target, refusing any non-test database."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("Set TEST_DATABASE_URL to a fresh disposable PostgreSQL 17 database.")
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not url.database.startswith("unshaken_foundation_test_"):
        pytest.fail("Integration tests refuse this database name.")
    return url


@pytest.fixture
def scratch_url(migrated_url):
    """Create an empty database on the test server and drop it afterwards."""
    name = "unshaken_foundation_test_ready_" + uuid4().hex[:8]
    admin = database_engine(migrated_url).execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield migrated_url.set(database=name)
    finally:
        pool.dispose_engine()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def client_for(monkeypatch, url):
    """Point the real app and its shared pool at one disposable database."""
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setattr(main, "initialize", lambda **_: False)
    monkeypatch.setattr(main, "shutdown", lambda: True)
    monkeypatch.setattr(health, "_last_readiness_state", "ready")
    pool.dispose_engine()
    return TestClient(main.app, raise_server_exceptions=False)


def build_lookups(url, categories=True, body_parts=True, active=True):
    """Create only the lookup tables a scenario needs, with one row each."""
    engine = database_engine(url)
    with engine.begin() as connection:
        for name, wanted in (("exercise_categories", categories), ("body_parts", body_parts)):
            if wanted:
                connection.exec_driver_sql(LOOKUP_TABLE.format(name=name))
                connection.exec_driver_sql(
                    f"INSERT INTO {name} VALUES (1, {'true' if active else 'false'})"
                )
    engine.dispose()


def assert_connections_released():
    """Wait briefly for an abandoned worker, then require an empty checkout count."""
    limit = time.monotonic() + 3
    while pool.shared_engine().pool.checkedout() and time.monotonic() < limit:
        time.sleep(0.02)
    assert pool.shared_engine().pool.checkedout() == 0


def assert_safe_503(response, code):
    assert response.status_code == 503
    assert response.json()["error"]["code"] == code
    for fragment in SECRET_FRAGMENTS:
        assert fragment not in response.text


def snapshot(url):
    """Capture lookup contents and every table name to prove nothing is written."""
    engine = database_engine(url)
    with engine.connect() as connection:
        rows = (
            connection.exec_driver_sql(
                "SELECT 'c', id, name, is_active FROM exercise_categories "
                "UNION ALL SELECT 'b', id, name, is_active FROM body_parts ORDER BY 1, 2"
            ).all(),
            connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"
            ).all(),
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").all(),
        )
    engine.dispose()
    return rows


def test_migrated_seeded_database_is_ready_and_unchanged(monkeypatch, migrated_url):
    before = snapshot(migrated_url)
    with client_for(monkeypatch, migrated_url) as client:
        for _ in range(40):
            response = client.get("/health/ready")
            assert response.status_code == 200
            assert response.json() == {"status": "ready"}
        assert_connections_released()
    assert snapshot(migrated_url) == before


def test_check_transaction_refuses_writes(migrated_url):
    """After the check's statements, the server itself rejects a write."""
    engine = database_engine(migrated_url)
    with engine.connect() as connection:
        assert readiness._has_active_choices(connection, 2000) is True
        with pytest.raises(sa.exc.InternalError, match="read-only transaction"):
            connection.exec_driver_sql("UPDATE body_parts SET is_active = is_active")
        connection.rollback()
    engine.dispose()


@pytest.mark.parametrize(
    "tables",
    [
        {"categories": False},
        {"body_parts": False},
        {"categories": False, "body_parts": False},
    ],
    ids=["no-categories", "no-body-parts", "neither"],
)
def test_missing_lookup_table(monkeypatch, scratch_url, tables):
    build_lookups(scratch_url, **tables)
    with client_for(monkeypatch, scratch_url) as client:
        assert_safe_503(client.get("/health/ready"), "reference_data_unavailable")
        assert client.get("/health/live").status_code == 200
        assert_connections_released()


def test_no_active_rows(monkeypatch, scratch_url):
    build_lookups(scratch_url, active=False)
    with client_for(monkeypatch, scratch_url) as client:
        assert_safe_503(client.get("/health/ready"), "reference_data_unavailable")
        assert_connections_released()


def test_one_empty_table(monkeypatch, scratch_url):
    build_lookups(scratch_url)
    engine = database_engine(scratch_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM body_parts")
    engine.dispose()
    with client_for(monkeypatch, scratch_url) as client:
        assert_safe_503(client.get("/health/ready"), "reference_data_unavailable")


def test_blocked_read_times_out_within_deadline_and_recovers(monkeypatch, scratch_url, capsys):
    """A live lock forces the read past the deadline; timing is printed as evidence."""
    build_lookups(scratch_url)
    locker = database_engine(scratch_url)
    with client_for(monkeypatch, scratch_url) as client:
        assert client.get("/health/ready").status_code == 200
        with locker.connect() as holder:
            holder.exec_driver_sql("LOCK TABLE body_parts IN ACCESS EXCLUSIVE MODE")
            started = time.monotonic()
            response = client.get("/health/ready")
            elapsed = time.monotonic() - started
            holder.rollback()
        with capsys.disabled():
            print(f"\nlive blocked-read readiness elapsed: {elapsed:.3f}s")
        assert_safe_503(response, "database_unavailable")
        assert elapsed < 3.0
        assert_connections_released()
        assert client.get("/health/ready").status_code == 200
    locker.dispose()


def test_pool_exhaustion_times_out_then_recovers(monkeypatch, scratch_url, capsys):
    build_lookups(scratch_url)
    with client_for(monkeypatch, scratch_url) as client:
        engine = pool.shared_engine()
        held = [engine.connect() for _ in range(engine.pool.size() + engine.pool._max_overflow)]
        started = time.monotonic()
        response = client.get("/health/ready")
        elapsed = time.monotonic() - started
        with capsys.disabled():
            print(f"\nlive pool-exhaustion readiness elapsed: {elapsed:.3f}s")
        assert_safe_503(response, "database_unavailable")
        assert elapsed < 3.0
        for connection in held:
            connection.close()
        assert client.get("/health/ready").status_code == 200
        assert_connections_released()


def test_refused_connection_is_safe_and_fast(monkeypatch, migrated_url, caplog, capsys):
    """A live refused connection: nothing listens on the chosen port."""
    closed = migrated_url.set(host="127.0.0.1", port=1)
    with client_for(monkeypatch, closed) as client:
        started = time.monotonic()
        response = client.get("/health/ready")
        elapsed = time.monotonic() - started
        assert_safe_503(response, "database_unavailable")
        assert client.get("/health/live").status_code == 200
    with capsys.disabled():
        print(f"\nlive refused-connection readiness elapsed: {elapsed:.3f}s")
    assert elapsed < 3.0
    assert migrated_url.password not in caplog.text
    assert migrated_url.host not in caplog.text


def test_shared_engine_targets_configured_database(monkeypatch, migrated_url):
    monkeypatch.setenv("DATABASE_URL", migrated_url.render_as_string(hide_password=False))
    pool.dispose_engine()
    engine = pool.shared_engine()
    assert engine is pool.shared_engine()
    assert engine.url.database == database_url().database
    assert isinstance(engine.pool, sa.pool.QueuePool)
    pool.dispose_engine()


def test_readiness_unchanged_with_unreachable_telemetry_exporter(migrated_url):
    """Real telemetry pointed at a dead endpoint does not change readiness.

    Runs in a fresh process so the real telemetry setup is used, not a no-op.
    The 503 case changes readiness state, so it also emits a telemetry event
    whose export fails. Port 9 has nothing listening.
    """
    code = """
import os
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response = client.get('/health/ready')
    assert response.status_code == int(os.environ['EXPECTED_STATUS']), response.status_code
    assert client.get('/health/live').status_code == 200
"""
    cases = ((migrated_url, "200"), (migrated_url.set(host="127.0.0.1", port=1), "503"))
    for url, expected in cases:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "DATABASE_URL": url.render_as_string(hide_password=False),
                "OTEL_SDK_DISABLED": "false",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9",
                "EXPECTED_STATUS": expected,
            },
        )
        assert result.returncode == 0, (expected, result.stderr[-1500:])
