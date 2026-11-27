"""Process-scoped authentication resources and pending credential cleanup."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.auth.providers import Providers
from app.auth.settings import AuthSettings, load_auth_settings

_LOG = logging.getLogger("app.auth.cleanup")


class AuthAccessFilter(logging.Filter):
    """Keep provider callback queries out of native Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Suppress auth request lines before formatters see their arguments."""
        args = record.args
        return not (
            isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str)
            and args[2].split("?", 1)[0].startswith("/api/v1/auth/")
        )


@dataclass(frozen=True)
class AuthRuntime:
    """Shared settings, database pool, and provider HTTP client."""

    settings: AuthSettings
    engine: Engine
    providers: Providers


def _clean(runtime: AuthRuntime) -> None:
    """Attempt one bounded batch, retrying a failure on the next cadence."""
    from app.db.auth_storage import clear_expired_apple_credentials

    try:
        with runtime.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL statement_timeout = '2s'")
            clear_expired_apple_credentials(connection)
    except SQLAlchemyError:
        _LOG.warning("apple_onboarding_cleanup_failed")


async def _periodic_cleanup(runtime: AuthRuntime) -> None:
    """Clean up at startup and then every five minutes."""
    while True:
        await asyncio.to_thread(_clean, runtime)
        await asyncio.sleep(300)


@asynccontextmanager
async def _authentication_runtime(app):
    """Own authentication resources when private runtime settings exist."""
    app.state.authentication = None
    try:
        settings = load_auth_settings()
        from app.db.config import database_url

        engine = create_engine(
            database_url(),
            hide_parameters=True,
            pool_size=4,
            max_overflow=0,
            pool_timeout=2,
            connect_args={"connect_timeout": 2,
                          "options": "-c statement_timeout=5000 -c lock_timeout=2000"},
        )
    except ValueError:
        yield
        return

    runtime = AuthRuntime(settings, engine, Providers(settings))
    app.state.authentication = runtime
    cleanup = asyncio.create_task(_periodic_cleanup(runtime))
    try:
        yield
    finally:
        cleanup.cancel()
        try:
            await cleanup
        except asyncio.CancelledError:
            pass
        runtime.providers.close()
        engine.dispose()
        app.state.authentication = None


@asynccontextmanager
async def authentication_runtime(app):
    """Suppress auth access lines even when provider settings are unavailable."""
    access_log = logging.getLogger("uvicorn.access")
    access_filter = AuthAccessFilter()
    access_log.addFilter(access_filter)
    try:
        async with _authentication_runtime(app):
            yield
    finally:
        access_log.removeFilter(access_filter)
