"""Load only the existing private DATABASE_URL convention."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[3]


def database_url() -> URL:
    """Read private settings without exposing them in errors or logging."""
    if "DATABASE_URL" not in os.environ:
        load_dotenv(ROOT / ".env", override=False)
    value = os.environ.get("DATABASE_URL", "")
    try:
        url = make_url(value)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError
        return url
    except Exception:
        raise ValueError("Set a valid private PostgreSQL DATABASE_URL; no connection details are displayed.") from None


def database_engine(url: URL | None = None):
    """Build a quiet engine with bounded connection time and hidden parameters."""
    return create_engine(url or database_url(), hide_parameters=True, connect_args={"connect_timeout": 5})
