"""Alembic uses the same backend configuration, never a second URL setting."""
from alembic import context
from app.db.config import database_engine
from app.db.schema import metadata
import os
import json

if context.is_offline_mode():
    raise RuntimeError("Offline execution is disabled; use unshaken-db plan to verify a target first.")

connection = context.config.attributes.get("connection")
if connection is not None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with database_engine().connect() as connection:
        from app.db.cli import migration_plan
        from app.db.config import database_url
        details, token = migration_plan(connection, database_url())
        print(json.dumps(details, indent=2))
        supplied = context.get_x_argument(as_dictionary=True).get("approve_target")
        options = context.config.cmd_opts
        action = options.cmd[0].__name__ if options and getattr(options, "cmd", None) else "programmatic"
        disposable = details["database"].startswith("unshaken_foundation_test_") and (
            context.config.attributes.get("disposable_test") is True or
            os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE") == "1")
        if action not in {"current", "check", "history", "heads", "show", "revision"} and not disposable and supplied != token:
            raise RuntimeError("Review unshaken-db plan and approve its target before applying migrations.")
        connection.commit()
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
