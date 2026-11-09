"""Later plan/catalog changes must not overwrite recorded workout history."""

from __future__ import annotations

from decimal import Decimal

import pytest
from psycopg import errors

from tests.helpers import (ensure_lookups, make_provider_exercise, make_session, make_session_exercise,
                           make_session_set, make_template, make_template_exercise, make_template_set,
                           make_user, minutes, one)


@pytest.fixture
def recorded_workout(db):
    ensure_lookups(db)
    user = make_user(db, "Lifter")
    ex = make_provider_exercise(db, "Bench Press")
    plan = make_template(db, user, "Push Day")
    te = make_template_exercise(db, plan, ex)
    ts = make_template_set(db, te, 1, reps=10, weight=50, unit="kg")
    session = make_session(db, user, plan, 1)
    se = make_session_exercise(db, session, ex, te)
    ss = make_session_set(db, se, 1, ts, reps=10, weight=50, unit="kg")
    # Performed: 8 reps at 52.5 lb, then the workout is finished.
    db.execute("UPDATE session_sets SET status='completed', actual_reps=8, actual_weight=52.5, weight_unit='lb', "
               "completed_at=%s, rest_started_at=%s WHERE id=%s", (minutes(5), minutes(5), ss))
    db.execute("UPDATE workout_sessions SET status='completed', finished_at=%s WHERE id=%s", (minutes(30), session))
    return dict(user=user, ex=ex, plan=plan, te=te, ts=ts, session=session, se=se, ss=ss)


def snapshot(db, w):
    return db.execute(
        "SELECT ss.target_reps_snapshot, ss.suggested_weight_snapshot, ss.suggested_weight_unit_snapshot, "
        "ss.actual_reps, ss.actual_weight, ss.weight_unit, ss.rest_seconds, se.name_snapshot, se.category_snapshot, "
        "s.name_snapshot, s.source_template_version FROM session_sets ss "
        "JOIN session_exercises se ON se.id=ss.session_exercise_id JOIN workout_sessions s ON s.id=se.session_id "
        "WHERE ss.id=%s", (w["ss"],)).fetchone()


def test_editing_the_plan_does_not_change_recorded_history(db, recorded_workout):
    w = recorded_workout
    before = snapshot(db, w)
    assert before[:3] == (10, Decimal("50.000"), "kg") and before[3:6] == (8, Decimal("52.500"), "lb")
    db.execute("UPDATE template_sets SET target_reps=12, suggested_weight=60, weight_unit='lb', rest_seconds=90 "
               "WHERE id=%s", (w["ts"],))
    db.execute("UPDATE workout_templates SET name='Renamed', version=2 WHERE id=%s", (w["plan"],))
    db.execute("UPDATE exercises SET name='Renamed Press', is_active=false WHERE id=%s", (w["ex"],))
    db.execute("UPDATE exercise_categories SET name='Renamed Category' WHERE id=1")
    assert snapshot(db, w) == before  # starting targets, actuals and snapshots untouched
    db.execute("UPDATE exercise_categories SET name='Barbell' WHERE id=1")


def test_archiving_a_plan_keeps_lineage(db, recorded_workout):
    w = recorded_workout
    db.execute("UPDATE workout_templates SET archived_at=now() WHERE id=%s", (w["plan"],))
    row = db.execute("SELECT source_template_id, source_template_version FROM workout_sessions WHERE id=%s",
                     (w["session"],)).fetchone()
    assert row == (w["plan"], 1)


def test_deleting_plan_rows_is_blocked_so_history_survives(db, recorded_workout):
    w = recorded_workout
    for sql, key in (("DELETE FROM template_sets WHERE id=%s", "ts"),
                     ("DELETE FROM template_exercises WHERE id=%s", "te"),
                     ("DELETE FROM workout_templates WHERE id=%s", "plan")):
        with pytest.raises(errors.ForeignKeyViolation):
            db.execute(sql, (w[key],))
    assert one(db, "SELECT count(*) FROM session_sets WHERE id=%s", w["ss"]) == 1


@pytest.mark.parametrize("sql", [
    "UPDATE session_sets SET target_reps_snapshot=99 WHERE id=%s",
    "UPDATE session_sets SET suggested_weight_snapshot=99 WHERE id=%s",
    "UPDATE session_sets SET suggested_weight_unit_snapshot='lb' WHERE id=%s",
    "UPDATE session_sets SET was_in_starting_plan=false WHERE id=%s",
])
def test_starting_plan_snapshots_are_immutable(db, recorded_workout, sql):
    with pytest.raises(errors.CheckViolation):
        db.execute(sql, (recorded_workout["ss"],))


def test_name_and_source_version_snapshots_are_immutable(db, recorded_workout):
    w = recorded_workout
    for sql, key in (("UPDATE session_exercises SET name_snapshot='x' WHERE id=%s", "se"),
                     ("UPDATE session_exercises SET category_snapshot='x' WHERE id=%s", "se"),
                     ("UPDATE workout_sessions SET name_snapshot='x' WHERE id=%s", "session"),
                     ("UPDATE workout_sessions SET source_template_version=7 WHERE id=%s", "session")):
        with pytest.raises(errors.CheckViolation):
            db.execute(sql, (w[key],))


def test_updated_at_is_maintained_by_trigger(db):
    import time
    user = make_user(db, "Trigger")
    before = one(db, "SELECT updated_at FROM users WHERE id=%s", user)
    time.sleep(0.05)
    db.execute("UPDATE users SET display_name='Renamed' WHERE id=%s", (user,))
    assert one(db, "SELECT updated_at FROM users WHERE id=%s", user) > before


def test_only_one_in_progress_workout_per_user(db):
    import psycopg
    import pytest
    user = make_user(db, "Busy")
    make_session(db, user)
    with pytest.raises(psycopg.errors.UniqueViolation):
        make_session(db, user)
    other = make_user(db, "Other")
    make_session(db, other)  # other users are unaffected
    make_session(db, user, status="completed", finished=minutes(30))  # history is unlimited
