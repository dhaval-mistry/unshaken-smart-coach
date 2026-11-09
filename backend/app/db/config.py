"""Database settings from private environment variables (never committed)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(RuntimeError):
    pass


def _is_placeholder(value: str | None) -> bool:
    return not value or value.strip().startswith("<<")


def load_env() -> None:
    """Load the private repository-root .env without overriding real env vars."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def get_database_url() -> URL:
    """Return the target URL. DATABASE_URL wins; else build from POSTGRES_* vars."""
    load_env()
    raw = os.environ.get("DATABASE_URL")
    if not _is_placeholder(raw):
        url = make_url(raw)
        if url.drivername in ("postgresql", "postgres"):
            url = url.set(drivername="postgresql+psycopg")
        return url
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    database = os.environ.get("POSTGRES_DB")
    if _is_placeholder(user) or _is_placeholder(database):
        raise ConfigError(
            "No database target configured. Set DATABASE_URL, or POSTGRES_USER, "
            "POSTGRES_PASSWORD and POSTGRES_DB, in your private .env."
        )
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=database,
    )


def describe_target(url: URL) -> str:
    """Nonsecret target label: host:port/database. Never includes credentials."""
    return f"{url.host or 'localhost'}:{url.port or 5432}/{url.database}"
