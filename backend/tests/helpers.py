from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def ensure_lookups(conn) -> None:
    conn.execute("INSERT INTO exercise_categories VALUES (1,'Barbell',1,true),(7,'Cardio',7,true) ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO body_parts VALUES (1,'None',1,true),(5,'Chest',5,true) ON CONFLICT DO NOTHING")


def make_user(conn, name="User") -> uuid.UUID:
    return one(conn, "INSERT INTO users (display_name, preferred_weight_unit, status) "
                     "VALUES (%s,'kg','active') RETURNING id", name)


def make_provider_exercise(conn, name="Bench Press", category=1) -> uuid.UUID:
    with conn.transaction():
        ex = one(conn, "INSERT INTO exercises (name, category_id, body_part_id, source_type) "
                       "VALUES (%s,%s,5,'provider') RETURNING id", name, category)
        conn.execute("INSERT INTO provider_exercises (exercise_id, provider_name, provider_exercise_id, last_synced_at) "
                     "VALUES (%s,'exercisedb',%s,now())", (ex, str(uuid.uuid4())))
    return ex


def make_custom_exercise(conn, owner, name="My Lift") -> uuid.UUID:
    with conn.transaction():
        ex = one(conn, "INSERT INTO exercises (name, category_id, body_part_id, source_type) "
                       "VALUES (%s,1,5,'custom') RETURNING id", name)
        conn.execute("INSERT INTO custom_exercises (exercise_id, created_by_user_id) VALUES (%s,%s)", (ex, owner))
    return ex


def make_template(conn, owner=None, name="Plan") -> uuid.UUID:
    kind = "personal" if owner else "sample"
    return one(conn, "INSERT INTO workout_templates (owner_user_id, template_type, name) "
                     "VALUES (%s,%s,%s) RETURNING id", owner, kind, name)


def make_template_exercise(conn, template, exercise, position=1) -> uuid.UUID:
    return one(conn, "INSERT INTO template_exercises (template_id, exercise_id, position) "
                     "VALUES (%s,%s,%s) RETURNING id", template, exercise, position)


def make_template_set(conn, te, number=1, reps=10, weight=50, unit="kg") -> uuid.UUID:
    return one(conn, "INSERT INTO template_sets (template_exercise_id, set_number, target_reps, suggested_weight, weight_unit) "
                     "VALUES (%s,%s,%s,%s,%s) RETURNING id", te, number, reps, weight, unit if weight is not None else None)


def make_session(conn, user, template=None, version=None, status="in_progress", finished=None) -> uuid.UUID:
    update_status = "pending" if template else "not_applicable"
    return one(conn, "INSERT INTO workout_sessions (user_id, source_template_id, source_template_version, name_snapshot, "
                     "status, started_at, finished_at, template_update_status) VALUES (%s,%s,%s,'Workout',%s,%s,%s,%s) RETURNING id",
               user, template, version, status, T0, finished, update_status)


def make_session_exercise(conn, session, exercise, source_te=None, position=1) -> uuid.UUID:
    return one(conn, "INSERT INTO session_exercises (session_id, exercise_id, source_template_exercise_id, name_snapshot, "
                     "category_snapshot, body_part_snapshot, position) VALUES (%s,%s,%s,'Bench Press','Barbell','Chest',%s) RETURNING id",
               session, exercise, source_te, position)


def make_session_set(conn, se, number=1, source_ts=None, starting=True, reps=10, weight=50, unit="kg") -> uuid.UUID:
    return one(conn, "INSERT INTO session_sets (session_exercise_id, source_template_set_id, set_number, target_reps_snapshot, "
                     "suggested_weight_snapshot, suggested_weight_unit_snapshot, status, was_in_starting_plan) "
                     "VALUES (%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING id",
               se, source_ts, number, reps if starting else None, weight if starting else None,
               unit if starting else None, starting)
