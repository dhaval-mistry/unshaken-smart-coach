"""Unit coverage for bounded PostgreSQL readiness state and resource cleanup."""

import asyncio
import threading
import time
from concurrent.futures import Future

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from app.db.readiness import (
    DatabaseReadiness,
    ReadinessState,
    _BoundedExecutor,
    _Cancellation,
)
import pytest


class FakeEngine:
    def __init__(self):
        self.checkout_attempted = False
        self.disposed = False

    def connect(self):
        self.checkout_attempted = True
        raise AssertionError("expired work must not reach pool checkout")

    def dispose(self, close=True):
        self.disposed = close


def test_expired_queued_work_never_checks_out():
    resources = DatabaseReadiness.__new__(DatabaseReadiness)
    resources._clock = lambda: 10.0
    resources._engine = FakeEngine()
    result = resources._check_sync(
        deadline=11.0,
        controller=_Cancellation(),
    )
    assert result == ReadinessState.DATABASE_UNAVAILABLE
    assert resources._engine.checkout_attempted is False


def test_invalid_database_url_resource_is_database_unavailable():
    resources = DatabaseReadiness(None)
    result = asyncio.run(resources.check())
    assert result.state == ReadinessState.DATABASE_UNAVAILABLE


def test_missing_table_maps_to_reference_data():
    exc = sa.exc.DBAPIError(
        "SELECT",
        {},
        type("MissingTable", (Exception,), {"sqlstate": "42P01"})(),
    )
    assert (
        DatabaseReadiness._classify_exception(exc)
        == ReadinessState.REFERENCE_DATA_UNAVAILABLE
    )


def test_missing_permission_maps_to_database_unavailable():
    exc = sa.exc.DBAPIError(
        "SELECT",
        {},
        type("MissingPermission", (Exception,), {"sqlstate": "42501"})(),
    )
    assert (
        DatabaseReadiness._classify_exception(exc)
        == ReadinessState.DATABASE_UNAVAILABLE
    )


def test_missing_column_maps_to_internal_error():
    exc = ProgrammingError("SELECT", {}, type("MissingColumn", (Exception,), {})())
    assert (
        DatabaseReadiness._classify_exception(exc)
        == ReadinessState.INTERNAL_ERROR
    )


def test_operational_failure_maps_to_database_unavailable():
    exc = OperationalError("SELECT", {}, type("Refused", (Exception,), {})())
    assert (
        DatabaseReadiness._classify_exception(exc)
        == ReadinessState.DATABASE_UNAVAILABLE
    )


def test_unexpected_database_error_maps_to_internal_error():
    exc = DBAPIError("SELECT", {}, type("Unexpected", (Exception,), {})())
    assert (
        DatabaseReadiness._classify_exception(exc)
        == ReadinessState.INTERNAL_ERROR
    )


def test_executor_capacity_is_bounded_and_fail_fast():
    executor = _BoundedExecutor()
    release = threading.Event()
    try:
        accepted = [
            executor.submit(release.wait)
            for _ in range(4)
        ]
        assert all(future is not None for future in accepted)
        assert executor.submit(release.wait) is None
    finally:
        release.set()
        executor.stop()


def test_cancellation_requests_supported_driver_cancel_and_marks_uncertain():
    cancellation = _Cancellation()

    class FakeDriver:
        def __init__(self):
            self.cancel_timeout = None

        def cancel_safe(self, timeout):
            self.cancel_timeout = timeout

    driver = FakeDriver()
    assert cancellation.attach(driver)
    cancellation.request(timeout=0.1)
    assert cancellation.requested is True
    assert cancellation.uncertain is True
    assert driver.cancel_timeout == 0.1
    cancellation.detach()


def test_request_after_attach_wins_and_connection_must_be_invalidated():
    cancellation = _Cancellation()
    cancellation.request(timeout=0.1)
    assert cancellation.attach(object()) is False
    assert cancellation.uncertain is True


def test_client_cancellation_stops_waiting_within_deadline():
    async def run_cancellation():
        resources = DatabaseReadiness(None)
        resources._engine = FakeEngine()
        future = Future()

        def submit(_function, *_args):
            return future

        resources._executor.submit = submit

        task = asyncio.create_task(resources.check())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("client cancellation did not propagate")
        assert resources._controllers == set()
        return resources

    resources = asyncio.run(run_cancellation())
    assert resources._closed is False


def test_shutdown_rejects_future_work_and_disposes_engine():
    resources = DatabaseReadiness(None)
    engine = FakeEngine()
    engine.checkout_attempted = False
    engine.disposed = False
    resources._engine = engine

    assert resources.shutdown() is True
    assert resources._closed is True
    assert engine.disposed is True
