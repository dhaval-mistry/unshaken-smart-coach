"""Create the reviewed 13-table PostgreSQL foundation and database guards."""
from pathlib import Path
import os
from alembic import op

revision = "0001_database_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Apply frozen SQL in the surrounding Alembic transaction."""
    bind = op.get_bind()
    with bind.connection.driver_connection.cursor() as cursor:
        for filename in ("0001_schema.sql", "0001_guards.sql"):
            cursor.execute(Path(__file__).with_name(filename).read_text(encoding="utf-8"))


def require_disposable():
    """Refuse destructive rollback unless explicitly enabled on a test database."""
    name = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE") != "1" or not name.startswith("unshaken_foundation_test_"):
        raise RuntimeError("Rollback is allowed only with explicit disposable-test authorization.")


def downgrade():
    """Drop this foundation only on an explicitly identified disposable database."""
    require_disposable()
    bind = op.get_bind()
    # Revoke guards before dropping their tables; each function is owned by this revision.
    bind.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    for table in ["session_sets","session_exercises","workout_sessions","template_sets","template_exercises","workout_templates","custom_exercises","provider_exercises","exercises","body_parts","exercise_categories","user_identities","users"]:
        bind.exec_driver_sql(f"DROP TABLE {table} CASCADE")
    for signature in ("usc_no_truncate()", "usc_validate_database()", "usc_write_guard()", "usc_historical_uuid(text,uuid)",
                      "usc_normalize_snapshot(jsonb)", "usc_snapshot(jsonb)",
                      "usc_measurement(text,integer,integer,numeric,boolean)", "usc_fail(text)"):
        bind.exec_driver_sql(f"DROP FUNCTION {signature}")
