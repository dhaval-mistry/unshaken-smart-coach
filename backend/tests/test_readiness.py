"""Unit coverage for bounded PostgreSQL readiness state and resource cleanup."""

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from app.db.readiness import (
    DatabaseReadiness,
    ReadinessState,
    _Cancellation,
)


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
