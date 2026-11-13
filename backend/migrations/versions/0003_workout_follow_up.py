"""Add effective exercise kinds and protected workout cancellation semantics.

The revision refuses incompatible legacy rows instead of repairing, deleting,
or reinterpreting history. Only the new exercise field is backfilled.
"""
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0003_workout_follow_up"
down_revision = "0002_master_records"
branch_labels = None
depends_on = None


def execute_script(sql):
    """Execute frozen multi-statement SQL without treating percent signs as binds."""
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql)


def lock_foundation():
    """Bound lock waiting and exclude legacy writes for preflight and DDL."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    bind.exec_driver_sql("SELECT pg_advisory_xact_lock(746231901)")
    bind.exec_driver_sql(
        "LOCK TABLE users,user_identities,exercise_categories,body_parts,exercises,"
        "provider_exercises,custom_exercises,workout_templates,template_exercises,"
        "template_sets,workout_sessions,session_exercises,session_sets "
        "IN ACCESS EXCLUSIVE MODE"
    )


def upgrade():
    """Preflight legacy rows, backfill effective kinds, and install new guards."""
    lock_foundation()
    bind = op.get_bind()
    conflicts = bind.exec_driver_sql("""
        SELECT
          (SELECT count(*) FROM public.workout_templates w WHERE NOT EXISTS
            (SELECT FROM public.template_exercises t WHERE t.template_id=w.id))
            AS empty_templates,
          (SELECT count(*) FROM public.template_exercises t WHERE NOT EXISTS
            (SELECT FROM public.template_sets s WHERE s.template_exercise_id=t.id))
            AS template_exercises_without_sets,
          (SELECT count(*) FROM public.template_sets s
            JOIN public.template_exercises t ON t.id=s.template_exercise_id
            JOIN public.exercises e ON e.id=t.exercise_id
            JOIN public.exercise_categories c ON c.id=e.category_id
            WHERE NOT public.usc_measurement(c.measurement_kind,s.target_reps,
              s.target_duration_seconds,s.target_distance_meters,true))
            AS invalid_template_targets,
          (SELECT count(*) FROM public.session_sets s
            JOIN public.session_exercises e ON e.id=s.session_exercise_id
            JOIN public.workout_sessions w ON w.id=e.session_id
            WHERE w.status='cancelled' AND s.status='pending')
            AS cancelled_sessions_with_pending_sets,
          (SELECT count(*) FROM public.exercises e
            JOIN public.exercise_categories c ON c.id=e.category_id
            WHERE c.id=4 AND c.measurement_kind NOT IN ('reps','duration'))
            AS incompatible_bodyweight_categories
    """).mappings().one()
    nonzero = [f"{category}={count}" for category, count in conflicts.items() if count]
    if nonzero:
        raise RuntimeError(
            "Workout migration conflicts: " + ", ".join(nonzero) + ". "
            "No legacy data was changed."
        )

    op.add_column("exercises", sa.Column("measurement_kind", sa.String(20)))
    bind.exec_driver_sql("ALTER TABLE exercises DISABLE TRIGGER usc_before_exercises")
    bind.exec_driver_sql("""
        UPDATE exercises e SET measurement_kind=c.measurement_kind
        FROM exercise_categories c WHERE c.id=e.category_id
    """)
    # Flush deferred legacy checks before DDL and before reenabling the trigger.
    bind.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    bind.exec_driver_sql("ALTER TABLE exercises ENABLE TRIGGER usc_before_exercises")
    bind.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
    op.alter_column("exercises", "measurement_kind", nullable=False)
    op.create_check_constraint("ck_exercises_measurement_kind", "exercises",
                               "measurement_kind IN ('reps','duration','duration_distance')")
    op.drop_constraint("ck_session_sets_1", "session_sets", type_="check")
    op.create_check_constraint("ck_session_sets_1", "session_sets",
                               "status IN ('pending','completed','skipped','cancelled')")
    op.create_check_constraint("ck_session_sets_cancelled_empty", "session_sets", """
        status <> 'cancelled' OR (actual_reps IS NULL AND actual_duration_seconds IS NULL
          AND actual_distance_meters IS NULL AND actual_weight IS NULL AND weight_unit IS NULL
          AND completed_at IS NULL AND rest_started_at IS NULL AND rest_ended_at IS NULL)
    """)
    execute_script(Path(__file__).with_name("0003_workout_guards.sql").read_text(encoding="utf-8"))
    execute_script(Path(__file__).with_name("0003_discard.sql").read_text(encoding="utf-8"))


def downgrade():
    """Restore 0002 only for an explicitly authorized compatible test database."""
    bind = op.get_bind()
    database = bind.exec_driver_sql("SELECT current_database()").scalar_one()
    if (os.environ.get("USC_ALLOW_DISPOSABLE_DOWNGRADE") != "1"
            or not database.startswith("unshaken_foundation_test_")):
        raise RuntimeError("Rollback is allowed only with explicit disposable-test authorization.")
    lock_foundation()
    if bind.exec_driver_sql("""
        SELECT EXISTS (SELECT FROM exercises e JOIN exercise_categories c ON c.id=e.category_id
          WHERE e.measurement_kind<>c.measurement_kind)
          OR EXISTS (SELECT FROM session_sets WHERE status='cancelled')
    """).scalar_one():
        raise RuntimeError("Rollback conflicts with effective kinds or cancelled history; no data was changed.")
    bind.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    legacy = Path(__file__).with_name("0001_guards.sql").read_text(encoding="utf-8")
    definitions = legacy[legacy.index("CREATE FUNCTION usc_write_guard()"):legacy.index("CREATE TRIGGER usc_before_users")]
    execute_script(definitions.replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION "))
    bind.exec_driver_sql("DROP FUNCTION public.usc_discard_active_session(uuid,uuid,boolean)")
    op.drop_constraint("ck_session_sets_cancelled_empty", "session_sets", type_="check")
    op.drop_constraint("ck_session_sets_1", "session_sets", type_="check")
    op.create_check_constraint("ck_session_sets_1", "session_sets", "status IN ('pending','completed','skipped')")
    op.drop_constraint("ck_exercises_measurement_kind", "exercises", type_="check")
    op.drop_column("exercises", "measurement_kind")
