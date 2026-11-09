"""Disposable-database fixtures.

Tests never touch the configured application database. They connect to the
same server only to CREATE and DROP a uniquely named throwaway database.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from alembic import command
from app.db.config import get_database_url
from app.db.migrate import alembic_config

PREFIX = "unshaken_disposable_"


def _psycopg_kwargs(url: URL, dbname: str) -> dict:
    return dict(host=url.host, port=url.port, user=url.username,
                password=url.password, dbname=dbname, autocommit=True)


@pytest.fixture(scope="session")
def server_url() -> URL:
    return get_database_url()


@pytest.fixture
def make_disposable_db(server_url):
    created: list[str] = []

    def _make() -> URL:
        name = PREFIX + uuid.uuid4().hex[:12]
        with psycopg.connect(**_psycopg_kwargs(server_url, server_url.database)) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return server_url.set(database=name)

    yield _make
    with psycopg.connect(**_psycopg_kwargs(server_url, server_url.database)) as admin:
        for name in created:
            assert name.startswith(PREFIX)  # only ever drop our own databases
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def migrate(url: URL, target: str = "head", down: bool = False) -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        cfg = alembic_config(conn)
        (command.downgrade if down else command.upgrade)(cfg, target)
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_url(server_url):
    """One fresh PostgreSQL database upgraded from empty to head."""
    name = PREFIX + uuid.uuid4().hex[:12]
    with psycopg.connect(**_psycopg_kwargs(server_url, server_url.database)) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = server_url.set(database=name)
    try:
        migrate(url)
        yield url
    finally:
        with psycopg.connect(**_psycopg_kwargs(server_url, server_url.database)) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def db(migrated_url):
    with psycopg.connect(**_psycopg_kwargs(migrated_url, migrated_url.database)) as conn:
        yield conn
