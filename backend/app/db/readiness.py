"""Bounded, read-only check of the reference data the exercise form needs.

The engine and driver are synchronous, so the check runs on a worker thread and
asyncio cancellation cannot interrupt it. Three bounds cooperate:

- The caller's asyncio deadline guarantees the HTTP response time.
- pool_timeout, connect_timeout, and server-side statement/lock timeouts end
  the normal slow cases on their own, returning the connection cleanly.
- If the caller gives up while a query is still blocked (for example, a frozen
  server that cannot run its own timeouts), the guard shuts down the socket so
  the driver call fails, the worker exits, and the pool discards the connection.
"""

import asyncio
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Literal

import psycopg
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc

from app.db import schema
from app.db.pool import shared_engine

Failure = Literal["database_unavailable", "reference_data_unavailable"]

UNDEFINED_TABLE = "42P01"

# Server timeouts fire slightly before the caller gives up, so the usual slow
# query ends with a clean cancel rather than a discarded connection.
SERVER_TIMEOUT_MARGIN_SECONDS = 0.1

# Readiness has its own small pool of threads: if checks hang they queue here
# and time out, and cannot consume the threads that serve liveness.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="readiness")


class _SocketGuard:
    """Let the caller break a worker's blocked read without touching other sockets.

    The guard holds a private duplicate of the driver's descriptor, taken at
    attach time. A descriptor number can be reused by an unrelated socket as
    soon as the driver closes its own copy (for example when SQLAlchemy
    invalidates the connection after a disconnect), so the guard never acts on
    the driver's number later. The duplicate always refers to this check's
    connection, and it is closed when the worker detaches.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._sock: socket.socket | None = None
        self._abandoned = False

    def attach(self, fd: int) -> bool:
        """Duplicate the worker's socket; return False if the caller already gave up."""
        with self._lock:
            if self._abandoned:
                return False
            try:
                self._sock = socket.socket(fileno=os.dup(fd))
            except OSError:
                return False  # Cannot guard this read, so do not start it.
            return True

    def detach(self) -> None:
        """Release the duplicate before the connection can return to the pool."""
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            sock.close()

    def abandon(self) -> None:
        """Mark the check abandoned and wake any read blocked on the socket.

        Shutting down the duplicate disconnects the underlying connection while
        the driver's own descriptor stays valid, so the driver sees an ordinary
        disconnect instead of a use-after-close.
        """
        with self._lock:
            self._abandoned = True
            if self._sock is None:
                return
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # Already disconnected; the worker is failing anyway.


def _has_active_choices(connection, timeout_ms: int) -> bool:
    """Read both lookup tables in a read-only transaction with server timeouts."""
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    # timeout_ms is an integer computed here, never caller input.
    connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
    connection.exec_driver_sql(f"SET LOCAL lock_timeout = {timeout_ms}")
    query = sa.select(
        sa.exists().where(schema.exercise_categories.c.is_active),
        sa.exists().where(schema.body_parts.c.is_active),
    )
    return all(connection.execute(query).one())


def _read_reference_data(guard: _SocketGuard, deadline: float) -> Failure | None:
    """Worker body: acquire, read, and release one connection; return the failure."""
    try:
        with shared_engine().connect() as connection:
            timeout_ms = int((deadline - time.monotonic() - SERVER_TIMEOUT_MARGIN_SECONDS) * 1000)
            socket_fd = connection.connection.driver_connection.pgconn.socket
            if timeout_ms <= 0 or not guard.attach(socket_fd):
                return "database_unavailable"
            try:
                has_choices = _has_active_choices(connection, timeout_ms)
                return None if has_choices else "reference_data_unavailable"
            finally:
                # End the transaction while the guard still covers this socket,
                # then detach before the pool can hand the connection to anyone.
                try:
                    connection.rollback()
                finally:
                    guard.detach()
    except sa_exc.ProgrammingError as error:
        if getattr(error.orig, "sqlstate", None) == UNDEFINED_TABLE:
            return "reference_data_unavailable"
        raise
    except (sa_exc.TimeoutError, sa_exc.OperationalError, sa_exc.InterfaceError, psycopg.OperationalError):
        return "database_unavailable"
    except sa_exc.DBAPIError as error:
        if error.connection_invalidated:
            return "database_unavailable"
        raise


async def check_readiness(deadline: float) -> Failure | None:
    """Run the check on a worker; the caller enforces the deadline by cancelling this."""
    guard = _SocketGuard()
    future = _executor.submit(_read_reference_data, guard, deadline)
    try:
        return await asyncio.wrap_future(future)
    finally:
        # Reached on success, failure, timeout, and client cancellation alike.
        guard.abandon()
        future.cancel()
