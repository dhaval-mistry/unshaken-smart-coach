"""One lazily created, process-wide SQLAlchemy engine for API database reads."""

from threading import Lock

from app.db.config import database_engine

# Pool wait and connection time for API requests. These stay under the
# three-second readiness total; 2 is libpq's minimum connect_timeout.
POOL_WAIT_SECONDS = 2.5
CONNECT_TIMEOUT_SECONDS = 2

_lock = Lock()
_engine = None


def shared_engine():
    """Return the one pooled engine, creating it (without connecting) on first use."""
    global _engine
    with _lock:
        if _engine is None:
            _engine = database_engine(
                connect_timeout=CONNECT_TIMEOUT_SECONDS, pool_timeout=POOL_WAIT_SECONDS
            )
        return _engine


def dispose_engine() -> None:
    """Close idle pooled connections and forget the engine; a later use recreates it."""
    global _engine
    with _lock:
        engine, _engine = _engine, None
    if engine is not None:
        engine.dispose()
