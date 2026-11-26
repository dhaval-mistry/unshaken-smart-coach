"""Validate container-only settings, then replace this process with its command."""

import os
import sys
from collections.abc import Sequence

from sqlalchemy.engine import make_url

_PLACEHOLDERS = {"APP_USER", "ENCODED_PASSWORD", "APP_DATABASE"}
_DATABASE_ERROR = (
    "Backend container refused to start: DATABASE_URL must be a private "
    "PostgreSQL URL for postgres:5432."
)


def _valid_container_database_url(value: str) -> bool:
    """Accept only a concrete PostgreSQL target on the private Compose network.

    This is structural validation, not a connectivity or readiness check. It
    prevents an unset, host-loopback, or checked-in example value from silently
    starting the backend while preserving liveness independence from PostgreSQL.
    """
    try:
        url = make_url(value)
    except Exception:
        return False

    fields = {url.username, url.password, url.database}
    return (
        url.drivername in {"postgresql", "postgresql+psycopg"}
        and url.host == "postgres"
        and (url.port or 5432) == 5432
        and all(fields)
        and not fields.intersection(_PLACEHOLDERS)
    )


def main(command: Sequence[str] | None = None) -> int:
    """Fail safely on invalid configuration, otherwise exec the requested command."""
    requested = list(sys.argv[1:] if command is None else command)
    if not _valid_container_database_url(os.environ.get("DATABASE_URL", "")):
        print(_DATABASE_ERROR, file=sys.stderr)
        return 2
    if not requested:
        print("Backend container refused to start: no command was provided.", file=sys.stderr)
        return 2

    try:
        # Replacing this process keeps Uvicorn as the direct service process and
        # preserves SIGTERM delivery; no shell or migration wrapper remains.
        os.execvp(requested[0], requested)
    except OSError:
        print("Backend container command could not be started.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
