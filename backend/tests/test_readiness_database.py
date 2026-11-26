"""Live PostgreSQL evidence for the bounded readiness resource.

These tests run only when the disposable runner supplies TEST_DATABASE_URL.
They never accept the shared/development database.
"""

import asyncio
import os
import time

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL

from app.db.config import database_engine, database_url
from app.db.readiness import DatabaseReadiness, ReadinessState


@pytest.fixture(scope="module")
def disposable_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("Set TEST_DATABASE_URL to a fresh disposable PostgreSQL 17 database.")
    os.environ["DATABASE_URL"] = value
    url = database_url()
    if not url.database.startswith("unshaken_foundation_test_"):
        pytest.fail("Readiness integration tests refuse this database name.")
    return url


@pytest.fixture
def engine(disposable_url):
    result = database_engine(disposable_url)
    yield result
    result.dispose()


def check(disposable_url):
    resources = DatabaseReadiness(disposable_url)
    try:
        return asyncio.run(resources.check())
    finally:
        resources.shutdown()


def check_resource(resources):
    return asyncio.run(resources.check())


def test_live_seeded_data_is_ready(engine, disposable_url):
    with engine.begin() as connection:
        category_count = connection.execute(
            sa.text("SELECT count(*) FROM exercise_categories WHERE is_active IS TRUE")
        ).scalar_one()
        body_count = connection.execute(
            sa.text("SELECT count(*) FROM body_parts WHERE is_active IS TRUE")
        ).scalar_one()
    assert category_count > 0
    assert body_count > 0
    assert check(disposable_url).state == ReadinessState.READY


def test_live_repeated_reads_reuse_pool_without_exhaustion(engine, disposable_url):
    resources = DatabaseReadiness(disposable_url)
    try:
        for _ in range(10):
            assert check_resource(resources).state == ReadinessState.READY
        assert resources._engine.pool.checkedout() == 0
    finally:
        resources.shutdown()


def test_live_empty_active_list_is_reference_unavailable(engine, disposable_url):
    with engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE exercise_categories SET is_active = FALSE")
        )
    try:
        result = check(disposable_url)
        assert result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE exercise_categories SET is_active = TRUE")
            )


def test_live_missing_table_is_reference_unavailable(engine, disposable_url):
    with engine.begin() as connection:
        connection.execute(sa.text("ALTER TABLE body_parts RENAME TO body_parts_hold"))
    try:
        result = check(disposable_url)
        assert result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text("ALTER TABLE body_parts_hold RENAME TO body_parts"))


def test_live_missing_column_is_internal_error(engine, disposable_url):
    with engine.begin() as connection:
        connection.execute(
            sa.text("ALTER TABLE exercise_categories DROP COLUMN is_active")
        )
    try:
        result = check(disposable_url)
        assert result.state == ReadinessState.INTERNAL_ERROR
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "ALTER TABLE exercise_categories "
                    "ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"
                )
            )


def test_live_lock_timeout_is_database_unavailable(engine, disposable_url):
    holder = engine.connect()
    holder.exec_driver_sql("BEGIN")
    holder.exec_driver_sql(
        "LOCK TABLE exercise_categories IN ACCESS EXCLUSIVE MODE"
    )
    try:
        result = check(disposable_url)
        assert result.state == ReadinessState.DATABASE_UNAVAILABLE
        assert result.elapsed_seconds < 3.0
    finally:
        holder.exec_driver_sql("ROLLBACK")
        holder.close()


def test_live_invalid_password_is_database_unavailable(disposable_url):
    invalid_url = disposable_url.set(
        password="intentional-wrong-password-usc-test"
    )
    resources = DatabaseReadiness(invalid_url)
    try:
        result = check_resource(resources)
        assert result.state == ReadinessState.DATABASE_UNAVAILABLE
        assert result.elapsed_seconds < 3.0
    finally:
        resources.shutdown()


def test_live_missing_permission_is_database_unavailable(engine, disposable_url):
    role = "usc_readiness_no_select"
    with engine.begin() as connection:
        connection.execute(sa.text(f'DROP ROLE IF EXISTS "{role}"'))
        connection.execute(sa.text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'usc-test-password\''))

    limited_url = URL.create(
        "postgresql+psycopg",
        username=role,
        password="usc-test-password",
        host=disposable_url.host,
        port=disposable_url.port,
        database=disposable_url.database,
    )
    resources = DatabaseReadiness(limited_url)
    try:
        result = check_resource(resources)
        assert result.state == ReadinessState.DATABASE_UNAVAILABLE
    finally:
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(f'DROP ROLE IF EXISTS "{role}"'))


def test_live_pool_exhaustion_is_database_unavailable(disposable_url):
    resources = DatabaseReadiness(disposable_url)
    held = []
    try:
        held.append(resources._engine.connect())
        held.append(resources._engine.connect())
        started = time.monotonic()
        result = check_resource(resources)
        elapsed = time.monotonic() - started
        assert result.state == ReadinessState.DATABASE_UNAVAILABLE
        assert elapsed < 3.0
        for connection in held:
            connection.close()
        held.clear()
        assert check_resource(resources).state == ReadinessState.READY
    finally:
        for connection in held:
            connection.close()
        resources.shutdown()


def test_live_refused_connect_is_database_unavailable(disposable_url):
    refused_url = URL.create(
        "postgresql+psycopg",
        username="nobody",
        password="wrong",
        host="127.0.0.1",
        port=1,
        database=disposable_url.database,
    )
    resources = DatabaseReadiness(refused_url)
    try:
        started = time.monotonic()
        result = check_resource(resources)
        assert result.state == ReadinessState.DATABASE_UNAVAILABLE
        assert time.monotonic() - started < 3.0
    finally:
        resources.shutdown()
