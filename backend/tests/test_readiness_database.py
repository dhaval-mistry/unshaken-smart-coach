"""Live PostgreSQL evidence for the bounded readiness resource.

These tests run only when the disposable runner supplies TEST_DATABASE_URL.
They never accept the shared/development database.
"""

import asyncio
import os
import time
import socket
import threading

import pytest
import sqlalchemy as sa
import httpx
import uvicorn
from sqlalchemy.engine import URL

from app.db.config import database_engine, database_url
from app.db.readiness import (
    DatabaseReadiness,
    ReadinessState,
)


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


def lookup_resource(resources, table_name):
    return asyncio.run(resources.lookup(table_name))


def start_lookup_http_server(resources):
    """Start the real FastAPI app on a loopback socket with a live resource."""
    from app import main

    main.initialize = lambda **_: False
    main.shutdown = lambda: True
    main.app.state.database_readiness = resources
    with socket.socket() as socket_handle:
        socket_handle.bind(("127.0.0.1", 0))
        port = socket_handle.getsockname()[1]
    config = uvicorn.Config(
        main.app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() >= deadline:
            server.should_exit = True
            thread.join(timeout=2)
            raise AssertionError("HTTP lookup server did not start.")
        time.sleep(0.01)
    return server, thread, f"http://127.0.0.1:{port}"


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


def test_live_lookup_lists_exact_initial_order_and_none(engine, disposable_url):
    resources = DatabaseReadiness(disposable_url)
    try:
        categories = lookup_resource(resources, "exercise_categories")
        parts = lookup_resource(resources, "body_parts")
        assert categories.state == ReadinessState.READY
        assert parts.state == ReadinessState.READY
        assert [item["name"] for item in categories.items] == [
            "Barbell", "Dumbbell", "Machine/Other", "Bodyweight",
            "Assisted Bodyweight", "Reps Only", "Cardio", "Duration",
        ]
        assert [item["name"] for item in parts.items] == [
            "None", "Arms", "Back", "Cardio", "Chest", "Core",
            "Full Body", "Legs", "Olympic", "Other", "Shoulders",
        ]
        assert all(type(item["id"]) is int for item in categories.items + parts.items)
        assert all(type(item["sort_order"]) is int for item in categories.items + parts.items)
        assert parts.items[0]["name"] == "None"
    finally:
        resources.shutdown()


def test_live_lookup_routes_return_real_http_lists(engine, disposable_url):
    resources = DatabaseReadiness(disposable_url)
    server = thread = base_url = None
    try:
        server, thread, base_url = start_lookup_http_server(resources)
        with httpx.Client(base_url=base_url, timeout=5) as client:
            categories = client.get("/api/v1/exercise-categories")
            parts = client.get("/api/v1/body-parts")

        assert categories.status_code == 200
        assert categories.headers["cache-control"] == "no-store"
        assert set(categories.json()) == {"items"}
        assert [item["name"] for item in categories.json()["items"]] == [
            "Barbell", "Dumbbell", "Machine/Other", "Bodyweight",
            "Assisted Bodyweight", "Reps Only", "Cardio", "Duration",
        ]
        assert parts.status_code == 200
        assert parts.headers["cache-control"] == "no-store"
        assert [item["name"] for item in parts.json()["items"]] == [
            "None", "Arms", "Back", "Cardio", "Chest", "Core",
            "Full Body", "Legs", "Olympic", "Other", "Shoulders",
        ]
    finally:
        if server is not None:
            server.should_exit = True
            if thread is not None:
                thread.join(timeout=5)
        resources.shutdown()


def test_live_lookup_order_is_sort_order_not_name_or_id(engine, disposable_url):
    with engine.begin() as connection:
        before = connection.execute(sa.text(
            "SELECT id, name, sort_order FROM exercise_categories ORDER BY id"
        )).mappings().all()
        connection.execute(sa.text(
            "UPDATE exercise_categories SET sort_order = id + 100"
        ))
        connection.execute(sa.text(
            "UPDATE exercise_categories SET sort_order = CASE name "
            "WHEN 'Barbell' THEN 8 "
            "WHEN 'Dumbbell' THEN 7 "
            "WHEN 'Machine/Other' THEN 6 "
            "WHEN 'Bodyweight' THEN 5 "
            "WHEN 'Assisted Bodyweight' THEN 4 "
            "WHEN 'Reps Only' THEN 3 "
            "WHEN 'Cardio' THEN 2 "
            "WHEN 'Duration' THEN 1 END"
        ))
    resources = DatabaseReadiness(disposable_url)
    try:
        result = lookup_resource(resources, "exercise_categories")
        assert result.state == ReadinessState.READY
        assert [item["name"] for item in result.items] == [
            "Duration", "Cardio", "Reps Only", "Assisted Bodyweight",
            "Bodyweight", "Machine/Other", "Dumbbell", "Barbell",
        ]
        assert [item["id"] for item in result.items] == [8, 7, 6, 5, 4, 3, 2, 1]
        # The approved schema keeps sort_order unique, so an id tie-break is
        # explicit in the query but no duplicate sort_order data is injected.
        import inspect
        source = inspect.getsource(DatabaseReadiness._lookup_sync)
        assert "ORDER BY sort_order ASC, id ASC" in source
    finally:
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE exercise_categories SET sort_order = id + 100"
            ))
            for row in before:
                connection.execute(
                    sa.text(
                        "UPDATE exercise_categories SET sort_order = :sort_order "
                        "WHERE id = :id"
                    ),
                    {"id": row["id"], "sort_order": row["sort_order"]},
                )


@pytest.mark.parametrize(
    ("table", "missing_column", "path"),
    [
        ("exercise_categories", "sort_order", "/api/v1/exercise-categories"),
        ("body_parts", "sort_order", "/api/v1/body-parts"),
    ],
)
def test_live_lookup_missing_column_route_is_safe_internal_error(
    engine, disposable_url, table, missing_column, path
):
    with engine.begin() as connection:
        original = connection.execute(sa.text(
            f"SELECT id, sort_order FROM {table} ORDER BY id"
        )).mappings().all()
    with engine.begin() as connection:
        connection.execute(sa.text(
            f"ALTER TABLE {table} DROP COLUMN {missing_column} CASCADE"
        ))
    resources = DatabaseReadiness(disposable_url)
    server = thread = None
    try:
        server, thread, base_url = start_lookup_http_server(resources)
        with httpx.Client(base_url=base_url, timeout=5) as client:
            response = client.get(path)
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["error"]["code"] == "internal_error"
        assert set(response.json()["error"]) == {"code", "message", "request_id"}
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    finally:
        if server is not None:
            server.should_exit = True
            if thread is not None:
                thread.join(timeout=5)
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(
                f"ALTER TABLE {table} "
                f"ADD COLUMN {missing_column} SMALLINT"
            ))
        with engine.begin() as connection:
            for row in original:
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET {missing_column} = :sort_order "
                        "WHERE id = :id"
                    ),
                    {"id": row["id"], "sort_order": row["sort_order"]},
                )
        with engine.begin() as connection:
            connection.execute(sa.text(
                f"ALTER TABLE {table} "
                f"ALTER COLUMN {missing_column} SET NOT NULL"
            ))
            connection.execute(sa.text(
                f"ALTER TABLE {table} "
                f"ADD CONSTRAINT uq_{table}_sort_order "
                f"UNIQUE ({missing_column})"
            ))


def test_live_lookup_omits_inactive_without_mutating_rows(engine, disposable_url):
    with engine.begin() as connection:
        before = connection.execute(sa.text(
            "SELECT id, name, sort_order, is_active "
            "FROM exercise_categories ORDER BY id"
        )).mappings().all()
        connection.execute(sa.text(
            "UPDATE exercise_categories SET is_active = FALSE "
            "WHERE name = 'Duration'"
        ))
    resources = DatabaseReadiness(disposable_url)
    try:
        categories = lookup_resource(resources, "exercise_categories")
        assert categories.state == ReadinessState.READY
        assert "Duration" not in [item["name"] for item in categories.items]
    finally:
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE exercise_categories SET is_active = TRUE "
                "WHERE name = 'Duration'"
            ))
            after = connection.execute(sa.text(
                "SELECT id, name, sort_order, is_active "
                "FROM exercise_categories ORDER BY id"
            )).mappings().all()
        assert [dict(row) for row in before] == [dict(row) for row in after]


def test_live_lookup_empty_list_is_reference_unavailable(engine, disposable_url):
    with engine.begin() as connection:
        connection.execute(sa.text(
            "UPDATE body_parts SET is_active = FALSE"
        ))
    resources = DatabaseReadiness(disposable_url)
    try:
        result = lookup_resource(resources, "body_parts")
        assert result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE
        assert result.items == ()
    finally:
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE body_parts SET is_active = TRUE"
            ))


def test_live_lookup_missing_table_is_reference_unavailable(engine, disposable_url):
    with engine.begin() as connection:
        connection.execute(sa.text(
            "ALTER TABLE body_parts RENAME TO body_parts_hold"
        ))
    resources = DatabaseReadiness(disposable_url)
    try:
        result = lookup_resource(resources, "body_parts")
        assert result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE
    finally:
        resources.shutdown()
        with engine.begin() as connection:
            connection.execute(sa.text(
                "ALTER TABLE body_parts_hold RENAME TO body_parts"
            ))


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
