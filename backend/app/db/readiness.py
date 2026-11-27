"""Bounded process-scoped PostgreSQL readiness resources for the API."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum

import sqlalchemy as sa
from psycopg import Connection as PsycopgConnection
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import (
    DBAPIError,
    OperationalError,
    ProgrammingError,
    TimeoutError as SATimeoutError,
)

from app.db.config import database_url

READINESS_DEADLINE_SECONDS = 3.0
RESPONSE_HEADROOM_SECONDS = 0.25
CLEANUP_HEADROOM_SECONDS = 0.50
CANCEL_TIMEOUT_SECONDS = 0.20
SHUTDOWN_TIMEOUT_SECONDS = 2.50
POOL_SIZE = 2
POOL_TIMEOUT_SECONDS = 0.75
EXECUTOR_WORKERS = 2
EXECUTOR_QUEUE_SIZE = 2
CONNECT_TIMEOUT_SECONDS = 1
MAX_STATEMENT_TIMEOUT_MS = 1_500
MIN_DATABASE_WORK_SECONDS = 0.05

_READINESS_QUERY = sa.text(
    """
    SELECT
      EXISTS (
        SELECT 1 FROM exercise_categories WHERE is_active IS TRUE LIMIT 1
      ) AS categories_available,
      EXISTS (
        SELECT 1 FROM body_parts WHERE is_active IS TRUE LIMIT 1
      ) AS body_parts_available
    """
)
_SET_STATEMENT_TIMEOUT = sa.text(
    "SELECT set_config('statement_timeout', :milliseconds, true)"
)
_LOGGER = logging.getLogger("app.database_readiness")


class ReadinessState(str, Enum):
    """Safe bounded outcomes understood by the HTTP layer."""

    READY = "ready"
    DATABASE_UNAVAILABLE = "database_unavailable"
    REFERENCE_DATA_UNAVAILABLE = "reference_data_unavailable"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ReadinessResult:
    """One readiness outcome with nonsecret elapsed-time evidence."""

    state: ReadinessState
    elapsed_seconds: float


@dataclass(frozen=True)
class LookupResult:
    """One public lookup outcome, including only safe serialized choices."""

    state: ReadinessState
    items: tuple[dict, ...]
    elapsed_seconds: float


class _Cancellation:
    """Coordinate supported driver cancellation with one synchronous worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._driver: PsycopgConnection | None = None
        self._requested = False
        self._uncertain = False

    @property
    def requested(self) -> bool:
        """Return whether the caller has abandoned or timed out the work."""
        with self._lock:
            return self._requested

    @property
    def uncertain(self) -> bool:
        """Return whether a checked-out driver connection must be invalidated."""
        with self._lock:
            return self._uncertain

    def attach(self, driver: PsycopgConnection) -> bool:
        """Expose an active driver unless cancellation already won the race."""
        with self._lock:
            if self._requested:
                self._uncertain = True
                return False
            self._driver = driver
            return True

    def detach(self) -> None:
        """Stop exposing a driver after its worker has completed cleanup."""
        with self._lock:
            self._driver = None

    def request(self, timeout: float = CANCEL_TIMEOUT_SECONDS) -> None:
        """Cancel an active Psycopg operation using its cross-platform API.

        `cancel_safe()` is intentionally called from the event-loop/shutdown
        thread while the database call runs in the bounded worker. Its own
        timeout bounds this short call. Merely cancelling the asyncio waiter
        would leave synchronous work holding the pool connection.
        """
        with self._lock:
            self._requested = True
            driver = self._driver
            if driver is not None:
                self._uncertain = True
        if driver is None:
            return
        try:
            driver.cancel_safe(timeout=max(0.01, timeout))
        except Exception:
            # The worker still has server/connect timeouts. The connection is
            # marked uncertain and will never be returned to the pool.
            return


class _BoundedExecutor:
    """ThreadPoolExecutor with a finite queue and fail-fast submissions."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=EXECUTOR_WORKERS,
            thread_name_prefix="usc-database",
        )
        self._slots = threading.BoundedSemaphore(
            EXECUTOR_WORKERS + EXECUTOR_QUEUE_SIZE
        )
        self._lock = threading.Lock()
        self._accepting = True
        self._futures: set[Future] = set()

    def submit(self, function, *args) -> Future | None:
        """Submit only when both lifecycle and bounded capacity permit it."""
        if not self._slots.acquire(blocking=False):
            return None
        with self._lock:
            if not self._accepting:
                self._slots.release()
                return None
            try:
                future = self._executor.submit(function, *args)
            except Exception:
                self._slots.release()
                return None
            self._futures.add(future)

        def completed(done: Future) -> None:
            with self._lock:
                self._futures.discard(done)
            self._slots.release()

        future.add_done_callback(completed)
        return future

    def stop(self) -> set[Future]:
        """Reject new work, cancel queued work, and return active snapshots."""
        with self._lock:
            self._accepting = False
            futures = set(self._futures)
        self._executor.shutdown(wait=False, cancel_futures=True)
        return futures


class DatabaseReadiness:
    """Own the API's single bounded engine, pool, executor, and shutdown."""

    def __init__(self, url: URL | None, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._executor = _BoundedExecutor()
        self._controllers_lock = threading.Lock()
        self._controllers: set[_Cancellation] = set()
        self._state_lock = threading.Lock()
        self._last_logged_state: ReadinessState | None = None
        self._closed = False
        self._engine = self._create_engine(url) if url is not None else None

    @classmethod
    def from_environment(cls) -> DatabaseReadiness:
        """Create resources without connecting, preserving liveness startup."""
        try:
            url = database_url()
        except ValueError:
            url = None
        return cls(url)

    @staticmethod
    def _create_engine(url: URL) -> Engine:
        """Create one fail-fast read-only pool without opening a connection."""
        return sa.create_engine(
            url,
            hide_parameters=True,
            pool_size=POOL_SIZE,
            max_overflow=0,
            pool_timeout=POOL_TIMEOUT_SECONDS,
            connect_args={
                "connect_timeout": CONNECT_TIMEOUT_SECONDS,
                "options": (
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={MAX_STATEMENT_TIMEOUT_MS} "
                    f"-c lock_timeout={MAX_STATEMENT_TIMEOUT_MS}"
                ),
            },
        )

    async def check(self) -> ReadinessResult:
        """Run one check inside a single three-second wall-clock deadline."""
        started = self._clock()
        deadline = started + READINESS_DEADLINE_SECONDS
        if self._engine is None or self._closed:
            return ReadinessResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                self._clock() - started,
            )

        controller = _Cancellation()
        with self._controllers_lock:
            if self._closed:
                return ReadinessResult(
                    ReadinessState.DATABASE_UNAVAILABLE,
                    self._clock() - started,
                )
            self._controllers.add(controller)

        future = self._executor.submit(self._check_sync, deadline, controller)
        if future is None:
            with self._controllers_lock:
                self._controllers.discard(controller)
            return ReadinessResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                self._clock() - started,
            )

        wrapped = asyncio.wrap_future(future)
        work_timeout = max(
            0.0,
            deadline
            - self._clock()
            - CLEANUP_HEADROOM_SECONDS
            - RESPONSE_HEADROOM_SECONDS,
        )
        try:
            result = await asyncio.wait_for(asyncio.shield(wrapped), work_timeout)
            return ReadinessResult(result, self._clock() - started)
        except asyncio.TimeoutError:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            return ReadinessResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                self._clock() - started,
            )
        except asyncio.CancelledError:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            raise
        except Exception:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            return ReadinessResult(ReadinessState.INTERNAL_ERROR, self._clock() - started)
        finally:
            with self._controllers_lock:
                self._controllers.discard(controller)

    async def lookup(self, table_name: str) -> LookupResult:
        """Read one lookup list on an independent three-second wall-clock deadline."""
        if table_name not in {"exercise_categories", "body_parts"}:
            return LookupResult(
                ReadinessState.INTERNAL_ERROR,
                (),
                0.0,
            )
        started = self._clock()
        deadline = started + READINESS_DEADLINE_SECONDS
        if self._engine is None or self._closed:
            return LookupResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                (),
                self._clock() - started,
            )

        controller = _Cancellation()
        with self._controllers_lock:
            if self._closed:
                return LookupResult(
                    ReadinessState.DATABASE_UNAVAILABLE,
                    (),
                    self._clock() - started,
                )
            self._controllers.add(controller)

        future = self._executor.submit(
            self._lookup_sync,
            table_name,
            deadline,
            controller,
        )
        if future is None:
            with self._controllers_lock:
                self._controllers.discard(controller)
            return LookupResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                (),
                self._clock() - started,
            )

        wrapped = asyncio.wrap_future(future)
        work_timeout = max(
            0.0,
            deadline
            - self._clock()
            - CLEANUP_HEADROOM_SECONDS
            - RESPONSE_HEADROOM_SECONDS,
        )
        try:
            state, items = await asyncio.wait_for(
                asyncio.shield(wrapped),
                work_timeout,
            )
            return LookupResult(
                state,
                tuple(items),
                self._clock() - started,
            )
        except asyncio.TimeoutError:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            return LookupResult(
                ReadinessState.DATABASE_UNAVAILABLE,
                (),
                self._clock() - started,
            )
        except asyncio.CancelledError:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            raise
        except Exception:
            await self._cancel_and_drain(future, wrapped, controller, deadline)
            return LookupResult(
                ReadinessState.INTERNAL_ERROR,
                (),
                self._clock() - started,
            )
        finally:
            with self._controllers_lock:
                self._controllers.discard(controller)

    def _lookup_sync(
        self,
        table_name: str,
        deadline: float,
        controller: _Cancellation,
    ) -> tuple[ReadinessState, list[dict]]:
        """Execute one fixed-table read within the caller's remaining budget."""
        remaining_before_checkout = (
            deadline
            - self._clock()
            - CLEANUP_HEADROOM_SECONDS
        )
        minimum_checkout_budget = (
            POOL_TIMEOUT_SECONDS
            + CONNECT_TIMEOUT_SECONDS
            + MIN_DATABASE_WORK_SECONDS
        )
        if remaining_before_checkout < minimum_checkout_budget:
            return ReadinessState.DATABASE_UNAVAILABLE, []

        connection = None
        invalidate = False
        try:
            connection = self._engine.connect()
            driver = connection.connection.driver_connection
            if not isinstance(driver, PsycopgConnection) or not controller.attach(driver):
                invalidate = True
                return ReadinessState.DATABASE_UNAVAILABLE, []

            remaining = deadline - self._clock() - CLEANUP_HEADROOM_SECONDS
            if remaining <= MIN_DATABASE_WORK_SECONDS or controller.requested:
                invalidate = controller.requested
                return ReadinessState.DATABASE_UNAVAILABLE, []

            statement_ms = max(
                1,
                min(MAX_STATEMENT_TIMEOUT_MS, int(remaining * 1_000)),
            )
            query = sa.text(
                f"SELECT id, name, sort_order "
                f"FROM {table_name} "
                f"WHERE is_active IS TRUE "
                f"ORDER BY sort_order ASC, id ASC"
            )
            with connection.begin():
                connection.execute(
                    _SET_STATEMENT_TIMEOUT,
                    {"milliseconds": f"{statement_ms}ms"},
                )
                rows = connection.execute(query).mappings().all()
            if not rows:
                return ReadinessState.REFERENCE_DATA_UNAVAILABLE, []
            items = [
                {
                    "id": int(row["id"]),
                    "name": str(row["name"]),
                    "sort_order": int(row["sort_order"]),
                }
                for row in rows
            ]
            return ReadinessState.READY, items
        except Exception as exc:
            invalidate = invalidate or controller.uncertain
            return self._classify_exception(exc), []
        finally:
            controller.detach()
            if connection is not None:
                try:
                    if invalidate or controller.uncertain:
                        connection.invalidate()
                    connection.close()
                except Exception:
                    pass

    async def _cancel_and_drain(
        self,
        future: Future,
        wrapped: asyncio.Future,
        controller: _Cancellation,
        deadline: float,
    ) -> None:
        """Stop queued/active work and reserve the remaining budget for cleanup."""
        future.cancel()
        remaining = max(0.01, deadline - self._clock() - RESPONSE_HEADROOM_SECONDS)
        controller.request(min(CANCEL_TIMEOUT_SECONDS, remaining))
        remaining = deadline - self._clock() - RESPONSE_HEADROOM_SECONDS
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(asyncio.shield(wrapped), remaining)
        except (asyncio.CancelledError, Exception):
            return

    def _check_sync(
        self,
        deadline: float,
        controller: _Cancellation,
    ) -> ReadinessState:
        """Checkout, read both active lists, and clean up in one worker."""
        remaining_before_checkout = (
            deadline
            - self._clock()
            - CLEANUP_HEADROOM_SECONDS
        )
        minimum_checkout_budget = (
            POOL_TIMEOUT_SECONDS
            + CONNECT_TIMEOUT_SECONDS
            + MIN_DATABASE_WORK_SECONDS
        )
        if remaining_before_checkout < minimum_checkout_budget:
            return ReadinessState.DATABASE_UNAVAILABLE

        connection = None
        invalidate = False
        try:
            connection = self._engine.connect()
            driver = connection.connection.driver_connection
            if not isinstance(driver, PsycopgConnection) or not controller.attach(driver):
                invalidate = True
                return ReadinessState.DATABASE_UNAVAILABLE

            remaining = deadline - self._clock() - CLEANUP_HEADROOM_SECONDS
            if remaining <= MIN_DATABASE_WORK_SECONDS or controller.requested:
                invalidate = controller.requested
                return ReadinessState.DATABASE_UNAVAILABLE

            statement_ms = max(
                1,
                min(MAX_STATEMENT_TIMEOUT_MS, int(remaining * 1_000)),
            )
            with connection.begin():
                connection.execute(
                    _SET_STATEMENT_TIMEOUT,
                    {"milliseconds": f"{statement_ms}ms"},
                )
                row = connection.execute(_READINESS_QUERY).one()
            if row.categories_available and row.body_parts_available:
                return ReadinessState.READY
            return ReadinessState.REFERENCE_DATA_UNAVAILABLE
        except Exception as exc:
            invalidate = invalidate or controller.uncertain
            return self._classify_exception(exc)
        finally:
            controller.detach()
            if connection is not None:
                try:
                    if invalidate or controller.uncertain:
                        connection.invalidate()
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _classify_exception(exc: Exception) -> ReadinessState:
        """Map driver/SQLAlchemy errors without exposing their text."""
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate == "42P01":
            return ReadinessState.REFERENCE_DATA_UNAVAILABLE
        if sqlstate in {"42501", "57014"}:
            return ReadinessState.DATABASE_UNAVAILABLE
        if sqlstate == "42703" or isinstance(exc, ProgrammingError):
            return ReadinessState.INTERNAL_ERROR
        if isinstance(exc, (OperationalError, SATimeoutError)):
            return ReadinessState.DATABASE_UNAVAILABLE
        if isinstance(exc, DBAPIError):
            return ReadinessState.INTERNAL_ERROR
        return ReadinessState.INTERNAL_ERROR

    def record_state(self, result: ReadinessResult, request_id: str) -> None:
        """Log only state transitions with allowlisted, nonsecret fields."""
        with self._state_lock:
            if result.state == self._last_logged_state:
                return
            self._last_logged_state = result.state
        _LOGGER.info(
            "database_readiness.state_changed",
            extra={
                "readiness_state": result.state.value,
                "request_id": request_id,
            },
        )

    def shutdown(self) -> bool:
        """Reject/cancel work, wait within a bound, then dispose the pool."""
        started = self._clock()
        with self._controllers_lock:
            self._closed = True
            controllers = list(self._controllers)
        for controller in controllers:
            remaining = SHUTDOWN_TIMEOUT_SECONDS - (self._clock() - started)
            if remaining <= 0:
                break
            controller.request(min(CANCEL_TIMEOUT_SECONDS, remaining))

        futures = self._executor.stop()
        remaining = max(0.0, SHUTDOWN_TIMEOUT_SECONDS - (self._clock() - started))
        _, unfinished = wait(futures, timeout=remaining)
        if self._engine is not None:
            self._engine.dispose(close=True)
        return not unfinished
