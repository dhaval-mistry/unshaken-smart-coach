from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from app.db.config import get_database_url

config = context.config


def run_migrations_online() -> None:
    # Tests and the CLI hand in an open connection to a specific database.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
