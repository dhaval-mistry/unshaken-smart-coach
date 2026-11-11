"""Small transactional database primitives; these are not workout APIs."""
import sqlalchemy as sa
from contextlib import contextmanager


def seal_starting_plan(connection, session_id):
    """Seal a complete initial plan inside the same transaction as its inserted rows."""
    result=connection.execute(sa.text("UPDATE workout_sessions SET starting_plan_snapshot=usc_snapshot(to_jsonb(workout_sessions)) WHERE id=:id AND starting_plan_snapshot IS NULL"),{"id":session_id})
    if result.rowcount!=1:
        raise ValueError("Capture is missing or already sealed.")


def complete_set(connection, set_id, user_id, **actuals):
    """Lock once, validate ownership, and preserve the original result on retry."""
    allowed={"actual_reps","actual_duration_seconds","actual_distance_meters","actual_weight","weight_unit"}
    if set(actuals)-allowed:
        raise ValueError("Unsupported completion field.")
    connection.exec_driver_sql("SELECT pg_advisory_xact_lock(746231901)")
    row=connection.execute(sa.text("SELECT s.* FROM session_sets s JOIN session_exercises e ON e.id=s.session_exercise_id JOIN workout_sessions w ON w.id=e.session_id WHERE s.id=:id AND w.user_id=:user FOR UPDATE OF s,w"),{"id":set_id,"user":user_id}).mappings().one_or_none()
    if row is None:
        raise ValueError("Set is unavailable to this user.")
    if row["status"]=="completed":
        return dict(row)
    if row["status"]!="pending":
        raise ValueError("Only pending sets may be completed.")
    assignments=", ".join(key+"=:"+key for key in actuals)
    if assignments:
        assignments+=", "
    # A single server timestamp is evaluated once and shared by both event columns.
    statement=("UPDATE session_sets SET "+assignments+
      "status='completed', completed_at=event.at, rest_started_at=event.at "
      "FROM (SELECT clock_timestamp() AS at) event WHERE id=:id RETURNING session_sets.*")
    return dict(connection.execute(sa.text(statement),dict(actuals,id=set_id)).mappings().one())


def save_cancelled_session(connection, session_id, user_id):
    """Retain performed work and cancel the owner's pending rows atomically.

    Authentication and transaction commit remain caller responsibilities. The
    shared database lock orders cancellation against completion and discard.
    """
    connection.exec_driver_sql("SELECT pg_advisory_xact_lock(746231901)")
    workout = connection.execute(sa.text(
        "SELECT * FROM workout_sessions WHERE id=:id AND user_id=:user FOR UPDATE"
    ), {"id": session_id, "user": user_id}).mappings().one_or_none()
    if workout is None or workout["status"] != "in_progress":
        raise ValueError("Only the owner's active workout can be cancelled.")
    connection.execute(sa.text(
        "UPDATE session_sets s SET status='cancelled' FROM session_exercises e "
        "WHERE s.session_exercise_id=e.id AND e.session_id=:id AND s.status='pending'"
    ), {"id": session_id})
    return dict(connection.execute(sa.text(
        "UPDATE workout_sessions SET status='cancelled',finished_at=clock_timestamp() "
        "WHERE id=:id RETURNING *"
    ), {"id": session_id}).mappings().one())


def discard_active_session(connection, session_id, user_id, *, confirmed=False):
    """Invoke the owner-only database primitive for a confirmed active discard.

    A future authenticated service must supply ``user_id`` from verified
    identity. The caller owns the surrounding transaction.
    """
    connection.execute(sa.text(
        "SELECT public.usc_discard_active_session(:id,:user,:confirmed)"
    ), {"id": session_id, "user": user_id, "confirmed": confirmed})


@contextmanager
def locked_template_update(connection, session_id, user_id):
    """Check source version before a later approved mapping operation changes the plan.

    Caller owns the transaction. Actual template-field mapping remains outside
    this foundation. A missing/version-changed source must be reported as a
    conflict in a separate durable transaction, never by erasing workout history.
    """
    connection.exec_driver_sql("SELECT pg_advisory_xact_lock(746231901)")
    workout=connection.execute(sa.text("SELECT * FROM workout_sessions WHERE id=:id AND user_id=:user FOR UPDATE"),
        {"id":session_id,"user":user_id}).mappings().one_or_none()
    if workout is None or workout["status"]!="completed" or workout["template_update_requested"] is not True or workout["template_update_status"]!="pending":
        raise ValueError("No approved pending template update is available.")
    source=connection.execute(sa.text("SELECT * FROM workout_templates WHERE id=:id FOR UPDATE"),
        {"id":workout["source_template_id"]}).mappings().one_or_none()
    if source is None or source["version"]!=workout["source_template_version"]:
        raise ValueError("Template source is unavailable or its version has changed.")
    yield dict(workout),dict(source)
