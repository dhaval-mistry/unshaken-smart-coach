"""Create the 13 approved application tables.

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).with_name("0001_create_application_tables.sql")

TABLES_IN_CREATE_ORDER = [
    "users", "user_identities", "exercise_categories", "body_parts", "exercises",
    "provider_exercises", "custom_exercises", "workout_templates", "template_exercises",
    "template_sets", "workout_sessions", "session_exercises", "session_sets",
]


def _run_script(sql: str) -> None:
    # Raw DBAPI cursor with no parameters: the script contains literal % signs
    # (RAISE/format) that must not be treated as parameter markers.
    op.get_bind().connection.cursor().execute(sql)


def upgrade() -> None:
    # Plain CREATE statements (no IF NOT EXISTS): a conflicting existing table
    # makes the whole transactional migration fail instead of being replaced.
    _run_script(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    """DESTRUCTIVE: drops all 13 tables and their data. Disposable databases only."""
    for table in reversed(TABLES_IN_CREATE_ORDER):
        _run_script(f"DROP TABLE IF EXISTS {table} CASCADE")
    _run_script(
        r"""
        DO $$
        DECLARE f record;
        BEGIN
            FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
                      JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = current_schema()
                       AND (p.proname LIKE 'fn\_%' OR p.proname LIKE 'trg\_%') LOOP
                EXECUTE 'DROP FUNCTION ' || f.sig || ' CASCADE';
            END LOOP;
        END $$;
        """
    )
