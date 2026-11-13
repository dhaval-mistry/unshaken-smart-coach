"""Issue #30 on disposable PostgreSQL 17, including genuine legacy upgrades.

These checks never connect to the development target. The imported session
fixture refuses non-test database names; lifecycle cases create sibling test
databases on that same disposable server. All examples are synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext

from app.db import schema as s
from app.db.cli import alembic_config
from app.db.config import database_engine
from app.db.operations import complete_set, discard_active_session, save_cancelled_session
from test_database import engine, exercise, new_disposable_database, rejects, session, template, user


@pytest.mark.parametrize("kind,actuals", [
    ("reps", {"actual_reps": 10}),
    ("duration", {"actual_duration_seconds": 45}),
])
def test_bodyweight_effective_kind_and_capture(engine, kind, actuals):
    """Both approved Bodyweight kinds drive templates, capture and actual checks."""
    with engine.begin() as c:
        owner = user(c)
        ex = exercise(c, owner=owner, category=4, kind=kind)
        plan = template(c, owner=owner, exercise_id=ex, category=4)
        _, workout, entry, st = session(c, owner=owner, source=plan)
        assert c.execute(sa.select(s.session_exercises.c.measurement_kind_snapshot)
                         .where(s.session_exercises.c.id == entry)).scalar_one() == kind
        saved = complete_set(c, st, owner, **actuals)
        assert saved["actual_reps"] == actuals.get("actual_reps")
        assert saved["actual_duration_seconds"] == actuals.get("actual_duration_seconds")
        snapshot = c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot)
                             .where(s.workout_sessions.c.id == workout)).scalar_one()
        assert snapshot["exercises"][0]["measurement_kind"] == kind


@pytest.mark.parametrize("category,kind", [(1, "duration"), (4, "duration_distance"),
                                          (5, "duration"), (7, "reps"), (8, "reps")])
def test_incompatible_exercise_kind(engine, category, kind):
    """The Bodyweight exception does not silently extend to other categories."""
    rejects(engine, lambda c: exercise(c, category=category, kind=kind))


def test_live_template_kind_edit_is_rejected(engine):
    """Unresolved catalog-edit semantics cannot reinterpret an existing live plan."""
    def operation(c):
        plan = template(c, category=4)
        c.execute(s.exercises.update().where(s.exercises.c.id == plan[1])
                  .values(measurement_kind="duration"))
    rejects(engine, operation)


SHADOWABLE_TABLES = tuple(s.metadata.tables)


def configure_shadow_writer(c):
    """Assume an ordinary table-writer role with attacker-controlled temp names."""
    role = "usc_shadow_writer_" + uuid4().hex[:10]
    c.exec_driver_sql("CREATE ROLE " + role)
    c.exec_driver_sql("GRANT USAGE ON SCHEMA public TO " + role)
    c.exec_driver_sql("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO " + role)
    c.exec_driver_sql("SET LOCAL ROLE " + role)
    for table_name in SHADOWABLE_TABLES:
        c.exec_driver_sql(
            f"CREATE TEMP TABLE {table_name} (LIKE public.{table_name} INCLUDING ALL)"
        )
    c.exec_driver_sql("SET LOCAL search_path=pg_temp,public")
    return role


def test_shadow_relations_cannot_bypass_referenced_kind_guard(engine):
    """A temp-schema attacker cannot make the D2 reference lookup vacuous."""
    with engine.begin() as c:
        plan = template(c, category=4)
        paths = c.exec_driver_sql("""
            SELECT proname, proconfig FROM pg_proc
            WHERE oid IN ('public.usc_write_guard()'::regprocedure,
                          'public.usc_validate_database()'::regprocedure)
        """).all()
        assert {name: config for name, config in paths} == {
            "usc_write_guard": ["search_path=pg_catalog, public, pg_temp"],
            "usc_validate_database": ["search_path=pg_catalog, public, pg_temp"],
        }
    with engine.connect() as c:
        tx = c.begin()
        try:
            configure_shadow_writer(c)
            with pytest.raises(sa.exc.IntegrityError):
                with c.begin_nested():
                    c.execute(sa.text(
                        "UPDATE public.exercises SET measurement_kind='duration' WHERE id=:id"
                    ), {"id": plan[1]})
            c.exec_driver_sql("RESET ROLE")
        finally:
            tx.rollback()
    with engine.connect() as c:
        assert c.execute(sa.select(s.exercises.c.measurement_kind)
                         .where(s.exercises.c.id == plan[1])).scalar_one() == "reps"
        saved = c.execute(sa.select(s.template_sets)
                          .where(s.template_sets.c.id == plan[3])).mappings().one()
        assert saved["target_reps"] == 8 and saved["target_duration_seconds"] is None


@pytest.mark.parametrize("case", ["last_set", "invalid_target", "category", "cancelled_active"])
def test_shadow_relations_cannot_bypass_deferred_validation(engine, case):
    """Public completeness, kind, and cancellation checks ignore temp shadows."""
    with engine.begin() as c:
        if case == "cancelled_active":
            owner, workout, _, row_id = session(c)
            original = ("session_set", row_id)
        else:
            plan = template(c)
            original = ("template_set", plan[3])

    with engine.connect() as c:
        tx = c.begin()
        try:
            configure_shadow_writer(c)
            with pytest.raises(sa.exc.IntegrityError):
                with c.begin_nested():
                    if case == "last_set":
                        c.execute(sa.text("DELETE FROM public.template_sets WHERE id=:id"),
                                  {"id": plan[3]})
                    elif case == "invalid_target":
                        c.execute(sa.text(
                            "UPDATE public.template_sets SET target_reps=NULL WHERE id=:id"
                        ), {"id": plan[3]})
                    elif case == "category":
                        c.execute(sa.text(
                            "UPDATE public.exercises SET category_id=7 WHERE id=:id"
                        ), {"id": plan[1]})
                    else:
                        c.execute(sa.text(
                            "UPDATE public.session_sets SET status='cancelled' WHERE id=:id"
                        ), {"id": row_id})
                    c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            c.exec_driver_sql("RESET ROLE")
        finally:
            tx.rollback()

    with engine.connect() as c:
        if original[0] == "template_set":
            row = c.execute(sa.select(s.template_sets)
                            .where(s.template_sets.c.id == original[1])).mappings().one()
            assert row["target_reps"] == 8
            assert c.execute(sa.select(s.exercises.c.category_id)
                             .where(s.exercises.c.id == plan[1])).scalar_one() == 1
        else:
            assert c.execute(sa.select(s.session_sets.c.status)
                             .where(s.session_sets.c.id == original[1])).scalar_one() == "pending"


def test_template_attach_and_kind_edit_serialize(engine):
    """D2 prevents a race from committing mismatched effective targets."""
    with engine.begin() as c:
        ex = exercise(c, category=4, kind="reps")

    def perform(action):
        """Run one side of the attach-versus-kind race in its own transaction."""
        try:
            with engine.begin() as c:
                if action == "attach":
                    template(c, exercise_id=ex, category=4)
                else:
                    c.execute(s.exercises.update().where(s.exercises.c.id == ex)
                              .values(measurement_kind="duration"))
            return True
        except sa.exc.IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        attached, changed = list(pool.map(perform, ["attach", "change"]))
    assert attached is True
    with engine.connect() as c:
        kind = c.execute(sa.select(s.exercises.c.measurement_kind)
                         .where(s.exercises.c.id == ex)).scalar_one()
        planned = c.execute(sa.select(s.template_sets).join(s.template_exercises)
                            .where(s.template_exercises.c.exercise_id == ex)).mappings().one()
        assert (kind, planned["target_reps"], planned["target_duration_seconds"]) in {
            ("reps", 8, None), ("duration", None, 600)
        }
        assert changed is (kind == "duration")


@pytest.mark.parametrize("case", ["empty", "zero_sets", "missing_target", "last_set", "last_exercise"])
def test_incomplete_template_rejected_atomically(engine, case):
    """Both initial saves and child edits/removals must leave a complete plan."""
    with engine.begin() as c:
        owner = user(c)
    def operation(c):
        if case == "empty":
            c.execute(s.workout_templates.insert().values(name="Incomplete synthetic plan",
                      template_type="personal", owner_user_id=owner))
            return
        plan = template(c, owner=owner)
        if case in ("zero_sets", "last_set"):
            c.execute(s.template_sets.delete().where(s.template_sets.c.id == plan[3]))
        elif case == "last_exercise":
            c.execute(s.template_exercises.delete().where(s.template_exercises.c.id == plan[2]))
        else:
            c.execute(s.template_sets.update().where(s.template_sets.c.id == plan[3])
                      .values(target_reps=None))
    rejects(engine, operation)
    with engine.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(s.workout_templates)
                         .where(s.workout_templates.c.owner_user_id == owner)).scalar_one() == 0


def test_failed_edit_preserves_previously_saved_template(engine):
    """A commit-time last-set failure leaves the previously published plan intact."""
    with engine.begin() as c:
        owner = user(c)
        plan = template(c, owner=owner)
    rejects(engine, lambda c: c.execute(s.template_sets.delete().where(s.template_sets.c.id == plan[3])))
    with engine.connect() as c:
        assert c.execute(sa.select(s.template_sets.c.target_reps)
                         .where(s.template_sets.c.id == plan[3])).scalar_one() == 8


def test_complete_template_children_can_be_built_and_replaced_atomically(engine):
    """Deferred checks allow a temporary gap within a single valid Save transaction."""
    with engine.begin() as c:
        plan = template(c)
        c.execute(s.template_sets.delete().where(s.template_sets.c.id == plan[3]))
        c.execute(s.template_sets.insert().values(template_exercise_id=plan[2], set_number=1, target_reps=12))
    with engine.begin() as c:
        c.execute(s.workout_templates.delete().where(s.workout_templates.c.id == plan[0]))


def cancel_fixture(c):
    """Build completed, pending and skipped rows while retaining initial evidence."""
    owner, workout, entry, st = session(c)
    completed = complete_set(c, st, owner, actual_reps=6, actual_weight=0, weight_unit="kg")
    pending = c.execute(s.session_sets.insert().values(session_exercise_id=entry,
        set_number=2, status="pending", was_in_starting_plan=False).returning(s.session_sets.c.id)).scalar_one()
    skipped = c.execute(s.session_sets.insert().values(session_exercise_id=entry,
        set_number=3, status="pending", was_in_starting_plan=False).returning(s.session_sets.c.id)).scalar_one()
    c.execute(s.session_sets.update().where(s.session_sets.c.id == skipped).values(status="skipped"))
    return owner, workout, entry, st, pending, skipped, completed


def test_cancel_save_preserves_results_and_frees_slot(engine):
    """Save keeps actuals/events and initial JSON, cancelling only pending sets."""
    with engine.begin() as c:
        owner, workout, entry, st, pending, skipped, completed = cancel_fixture(c)
        snapshot = c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot)
                             .where(s.workout_sessions.c.id == workout)).scalar_one()
        saved = save_cancelled_session(c, workout, owner)
        assert saved["status"] == "cancelled" and saved["finished_at"] is not None
        assert saved["starting_plan_snapshot"] == snapshot
        assert dict(c.execute(sa.select(s.session_sets).where(s.session_sets.c.id == st)).mappings().one()) == completed
        assert c.execute(sa.select(s.session_sets.c.status).where(s.session_sets.c.id == skipped)).scalar_one() == "skipped"
        row = c.execute(sa.select(s.session_sets).where(s.session_sets.c.id == pending)).mappings().one()
        assert row["status"] == "cancelled" and row["actual_reps"] is None
        assert row["completed_at"] is None and row["rest_started_at"] is None
        session(c, owner=owner)


@pytest.mark.parametrize("case", ["set_delete", "session_delete", "exercise_delete", "rewind",
                                  "actual_edit", "notes_edit", "discard"])
def test_saved_partial_history_is_protected(engine, case):
    """Saved partial history cannot be discarded, resumed, edited or deleted."""
    def operation(c):
        owner, workout, entry, st, pending, skipped, completed = cancel_fixture(c)
        save_cancelled_session(c, workout, owner)
        if case == "set_delete":
            c.execute(s.session_sets.delete().where(s.session_sets.c.id == pending))
        elif case == "session_delete":
            c.execute(s.workout_sessions.delete().where(s.workout_sessions.c.id == workout))
        elif case == "exercise_delete":
            c.execute(s.session_exercises.delete().where(s.session_exercises.c.id == entry))
        elif case == "rewind":
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id == workout)
                      .values(status="in_progress", finished_at=None))
        elif case == "actual_edit":
            c.execute(s.session_sets.update().where(s.session_sets.c.id == st).values(actual_reps=100))
        elif case == "notes_edit":
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id == workout).values(notes="rewrite"))
        else:
            discard_active_session(c, workout, owner, confirmed=True)
    rejects(engine, operation)


@pytest.mark.parametrize("case", ["pending_in_terminal", "cancelled_in_active", "actuals_in_cancelled"])
def test_inconsistent_cancel_state_rejected(engine, case):
    """Cancelled sets are empty and belong only to a fully transitioned partial save."""
    def operation(c):
        owner, workout, entry, st = session(c)
        if case == "pending_in_terminal":
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id == workout)
                      .values(status="cancelled", finished_at=sa.func.clock_timestamp()))
        elif case == "cancelled_in_active":
            c.execute(s.session_sets.update().where(s.session_sets.c.id == st).values(status="cancelled"))
        else:
            c.execute(s.session_sets.update().where(s.session_sets.c.id == st).values(actual_reps=3))
            save_cancelled_session(c, workout, owner)
    rejects(engine, operation)


@pytest.mark.parametrize("field,value", [("actual_reps", 2), ("actual_duration_seconds", 2),
    ("actual_distance_meters", 2), ("actual_weight", 0), ("weight_unit", "kg"),
    ("completed_at", sa.func.clock_timestamp()), ("rest_started_at", sa.func.clock_timestamp()),
    ("rest_ended_at", sa.func.clock_timestamp())])
def test_cancelled_set_cannot_hold_performance_or_events(engine, field, value):
    """Every actual/unit/event field is forbidden on an unfinished cancelled set."""
    def operation(c):
        owner, workout, _, st = session(c)
        c.execute(s.session_sets.update().where(s.session_sets.c.id == st)
                  .values(status="cancelled", **{field: value}))
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id == workout)
                  .values(status="cancelled", finished_at=sa.func.clock_timestamp()))
    rejects(engine, operation)


def test_saved_partial_survives_source_detachment(engine):
    """Immutable partial history still permits only legitimate live-FK detachment."""
    with engine.begin() as c:
        owner = user(c)
        plan = template(c, owner=owner)
        _, workout, entry, st = session(c, owner=owner, source=plan)
        saved = save_cancelled_session(c, workout, owner)
        c.execute(s.workout_templates.delete().where(s.workout_templates.c.id == plan[0]))
        c.execute(s.exercises.delete().where(s.exercises.c.id == plan[1]))
        row = c.execute(sa.select(s.workout_sessions).where(s.workout_sessions.c.id == workout)).mappings().one()
        assert row["starting_plan_snapshot"] == saved["starting_plan_snapshot"]
        assert row["source_template_id"] is None and row["source_template_id_snapshot"] == plan[0]
        assert c.execute(sa.select(s.session_sets.c.status).where(s.session_sets.c.id == st)).scalar_one() == "cancelled"


def test_historical_effective_kind_does_not_follow_later_catalog_edits(engine):
    """A later timed catalog definition cannot reinterpret an earlier reps snapshot."""
    with engine.begin() as c:
        owner = user(c)
        ex = exercise(c, category=4)
        _, workout, entry, st = session(c, owner=owner, ex=ex)
        original = c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot)
                             .where(s.workout_sessions.c.id == workout)).scalar_one()
        c.execute(s.exercises.update().where(s.exercises.c.id == ex).values(measurement_kind="duration"))
        assert complete_set(c, st, owner, actual_reps=4)["actual_reps"] == 4
        assert c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot)
                         .where(s.workout_sessions.c.id == workout)).scalar_one() == original
        _, _, new_entry, new_set = session(c, ex=ex)
        assert c.execute(sa.select(s.session_exercises.c.measurement_kind_snapshot)
                         .where(s.session_exercises.c.id == new_entry)).scalar_one() == "duration"


def test_confirmed_discard_removes_only_owned_active_draft(engine):
    """Discard removes performed draft children and releases only that active slot."""
    with engine.begin() as c:
        owner, workout, entry, st, pending, skipped, completed = cancel_fixture(c)
        other, other_workout, _, _ = session(c)
        discard_active_session(c, workout, owner, confirmed=True)
        assert c.execute(sa.select(s.workout_sessions.c.id).where(s.workout_sessions.c.id == workout)).first() is None
        assert c.execute(sa.select(s.session_exercises.c.id).where(s.session_exercises.c.id == entry)).first() is None
        assert c.execute(sa.select(s.session_sets.c.id).where(s.session_sets.c.id.in_([st, pending, skipped]))).first() is None
        assert c.execute(sa.select(s.workout_sessions.c.id).where(s.workout_sessions.c.id == other_workout)).scalar_one() == other_workout
        session(c, owner=owner)


@pytest.mark.parametrize("case", ["unconfirmed", "wrong_owner", "terminal"])
def test_discard_rejects_missing_confirmation_owner_or_terminal(engine, case):
    """The scoped function independently checks ownership, status and confirmation."""
    def operation(c):
        owner, workout, _, _ = session(c)
        if case == "terminal":
            save_cancelled_session(c, workout, owner)
        discard_active_session(c, workout, user(c) if case == "wrong_owner" else owner,
                               confirmed=case != "unconfirmed")
    rejects(engine, operation)


def test_discard_failure_rolls_back_entire_draft(engine):
    """The caller transaction can roll back discard without losing any child rows."""
    with engine.begin() as c:
        owner, workout, entry, st, pending, skipped, completed = cancel_fixture(c)
    with pytest.raises(RuntimeError, match="Synthetic"):
        with engine.begin() as c:
            discard_active_session(c, workout, owner, confirmed=True)
            raise RuntimeError("Synthetic later failure")
    with engine.connect() as c:
        assert c.execute(sa.select(s.workout_sessions.c.status).where(s.workout_sessions.c.id == workout)).scalar_one() == "in_progress"
        assert c.execute(sa.select(sa.func.count()).select_from(s.session_sets)
                         .where(s.session_sets.c.session_exercise_id == entry)).scalar_one() == 3


def test_discard_and_completion_serialize(engine):
    """A completion race cannot survive after the active draft is discarded."""
    with engine.begin() as c:
        owner, workout, _, st = session(c)

    def perform(action):
        """Run one side of the completion-versus-discard race."""
        try:
            with engine.begin() as c:
                if action == "complete":
                    complete_set(c, st, owner, actual_reps=5)
                else:
                    discard_active_session(c, workout, owner, confirmed=True)
            return True
        except (ValueError, sa.exc.IntegrityError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(perform, ["complete", "discard"]))
    assert outcomes[1] is True
    with engine.connect() as c:
        assert c.execute(sa.select(s.workout_sessions.c.id)
                         .where(s.workout_sessions.c.id == workout)).first() is None
        assert c.execute(sa.select(s.session_sets.c.id)
                         .where(s.session_sets.c.id == st)).first() is None


def test_ordinary_writer_cannot_execute_or_forge_discard(engine):
    """PUBLIC lacks EXECUTE and a forged transaction flag cannot enable deletion."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            owner, workout, entry, st, pending, skipped, completed = cancel_fixture(c)
            role = "usc_test_writer_" + uuid4().hex[:10]
            c.exec_driver_sql("CREATE ROLE " + role)
            c.exec_driver_sql("GRANT USAGE ON SCHEMA public TO " + role)
            c.exec_driver_sql("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO " + role)
            assert c.execute(sa.text(
                "SELECT has_function_privilege(:role, "
                "'public.usc_discard_active_session(uuid,uuid,boolean)', 'EXECUTE')",
            ), {"role": role}
            ).scalar_one() is False
            c.exec_driver_sql("SET LOCAL ROLE " + role)
            c.execute(sa.text("SELECT set_config('usc.discard_session_id',:id,true)"), {"id": str(workout)})
            with pytest.raises(sa.exc.IntegrityError):
                with c.begin_nested():
                    c.execute(s.session_sets.delete().where(s.session_sets.c.id == st))
            with pytest.raises(sa.exc.ProgrammingError):
                with c.begin_nested():
                    discard_active_session(c, workout, owner, confirmed=True)
            c.exec_driver_sql("RESET ROLE")
            assert c.execute(sa.select(s.workout_sessions.c.id)
                             .where(s.workout_sessions.c.id == workout)).scalar_one() == workout
        finally:
            tx.rollback()


def legacy_fixture(c, *, incomplete=False, cancelled=False, category=4):
    """Create representative revision-0002 data using its actual earlier columns."""
    owner = c.exec_driver_sql("INSERT INTO users(display_name,preferred_weight_unit,status) VALUES ('Synthetic legacy','kg','active') RETURNING id").scalar_one()
    category_name, kind = c.execute(sa.text("SELECT name,measurement_kind FROM exercise_categories WHERE id=:id"), {"id": category}).one()
    ex = c.execute(sa.text("INSERT INTO exercises(name,category_id,body_part_id,source_type) VALUES ('Legacy exercise',:category,1,'provider') RETURNING id"), {"category": category}).scalar_one()
    c.execute(sa.text("INSERT INTO provider_exercises(exercise_id,provider_name,provider_exercise_id,last_synced_at) VALUES (:id,'synthetic',:key,now())"), {"id": ex, "key": str(ex)})
    plan = c.execute(sa.text("INSERT INTO workout_templates(name,template_type,owner_user_id) VALUES ('Legacy plan','personal',:owner) RETURNING id"), {"owner": owner}).scalar_one()
    te = c.execute(sa.text("INSERT INTO template_exercises(template_id,exercise_id,position) VALUES (:plan,:ex,1) RETURNING id"), {"plan": plan, "ex": ex}).scalar_one()
    targets = {"reps": 8, "duration": None, "distance": None} if kind == "reps" else {
        "reps": None, "duration": 45, "distance": 100 if kind == "duration_distance" else None}
    if incomplete:
        targets = dict.fromkeys(targets)
    c.execute(sa.text("INSERT INTO template_sets(template_exercise_id,set_number,target_reps,target_duration_seconds,target_distance_meters) VALUES (:id,1,:reps,:duration,:distance)"), dict(targets, id=te))
    workout = c.execute(sa.text("INSERT INTO workout_sessions(user_id,name_snapshot,status,template_update_status) VALUES (:owner,'Legacy history','in_progress','not_applicable') RETURNING id"), {"owner": owner}).scalar_one()
    se = c.execute(sa.text("INSERT INTO session_exercises(session_id,exercise_id,exercise_id_snapshot,exercise_source_type_snapshot,name_snapshot,category_snapshot,body_part_snapshot,measurement_kind_snapshot,position) VALUES (:workout,:ex,:ex,'provider','Legacy exercise',:category,'None',:kind,1) RETURNING id"), {"workout": workout, "ex": ex, "category": category_name, "kind": kind}).scalar_one()
    st = c.execute(sa.text("INSERT INTO session_sets(session_exercise_id,set_number,status,was_in_starting_plan) VALUES (:id,1,'pending',true) RETURNING id"), {"id": se}).scalar_one()
    c.execute(sa.text("UPDATE workout_sessions SET starting_plan_snapshot=usc_snapshot(to_jsonb(workout_sessions)) WHERE id=:id"), {"id": workout})
    if not cancelled:
        actuals = {"actual_reps": 8} if kind == "reps" else {"actual_duration_seconds": 45}
        if kind == "duration_distance":
            actuals["actual_distance_meters"] = 100
        complete_set(c, st, owner, **actuals)
    c.execute(sa.text("UPDATE workout_sessions SET status=:status,finished_at=clock_timestamp() WHERE id=:id"), {"id": workout, "status": "cancelled" if cancelled else "completed"})
    return ex, workout


def legacy_template_preflight_conflict(c, case):
    """Create one 0002 template conflict without using post-0002 columns."""
    owner = c.exec_driver_sql(
        "INSERT INTO users(display_name,preferred_weight_unit,status) "
        "VALUES ('Synthetic preflight','kg','active') RETURNING id"
    ).scalar_one()
    plan = c.execute(sa.text(
        "INSERT INTO workout_templates(name,template_type,owner_user_id) "
        "VALUES ('Preflight plan','personal',:owner) RETURNING id"
    ), {"owner": owner}).scalar_one()
    if case == "empty_template":
        return
    ex = c.exec_driver_sql(
        "INSERT INTO exercises(name,category_id,body_part_id,source_type) "
        "VALUES ('Preflight exercise',1,1,'provider') RETURNING id"
    ).scalar_one()
    c.execute(sa.text(
        "INSERT INTO provider_exercises(exercise_id,provider_name,provider_exercise_id,last_synced_at) "
        "VALUES (:id,'synthetic',:key,now())"
    ), {"id": ex, "key": str(ex)})
    c.execute(sa.text(
        "INSERT INTO template_exercises(template_id,exercise_id,position) "
        "VALUES (:plan,:exercise,1)"
    ), {"plan": plan, "exercise": ex})


def capture_legacy_rows(c):
    """Capture exact pre-existing values, excluding only the newly backfilled field."""
    return {table: c.exec_driver_sql(
        f"SELECT COALESCE(jsonb_agg(to_jsonb(t) - 'measurement_kind' ORDER BY id),'[]') FROM {table} t"
        if table == "exercises" else
        f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY id),'[]') FROM {table} t"
    ).scalar_one() for table in ("exercises", "workout_templates", "template_exercises", "template_sets",
                                "workout_sessions", "session_exercises", "session_sets", "exercise_categories", "body_parts")}


def test_upgrade_preserves_legacy_values_and_original_kind(engine, monkeypatch):
    """Revision-0002 data upgrades without changing timestamps, seeds or history."""
    url = new_disposable_database(engine, "workout_upgrade")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        cfg = alembic_config()
        cfg.attributes["disposable_test"] = True
        command.upgrade(cfg, "0002_master_records")
        db = database_engine(url)
        try:
            with db.begin() as c:
                ex, workout = legacy_fixture(c)
                for category in (1, 7, 8):
                    legacy_fixture(c, category=category)
            with db.connect() as c:
                before = capture_legacy_rows(c)
            command.upgrade(cfg, "head")
            command.upgrade(cfg, "head")
            with db.connect() as c:
                assert capture_legacy_rows(c) == before
                assert c.execute(sa.select(s.exercises.c.measurement_kind).where(s.exercises.c.id == ex)).scalar_one() == "reps"
                assert c.exec_driver_sql("SELECT bool_and(e.measurement_kind=c.measurement_kind) FROM exercises e JOIN exercise_categories c ON c.id=e.category_id").scalar_one() is True
                assert MigrationContext.configure(c).get_current_revision() == "0003_workout_follow_up"
            command.check(cfg)
            patch.setenv("USC_ALLOW_DISPOSABLE_DOWNGRADE", "1")
            command.downgrade(cfg, "0002_master_records")
            command.upgrade(cfg, "head")
            with db.connect() as c:
                assert capture_legacy_rows(c) == before
        finally:
            db.dispose()


@pytest.mark.parametrize(("case", "category"), [
    ("empty_template", "empty_templates"),
    ("zero_sets", "template_exercises_without_sets"),
    ("invalid_target", "invalid_template_targets"),
    ("cancelled_pending", "cancelled_sessions_with_pending_sets"),
    ("bodyweight_kind", "incompatible_bodyweight_categories"),
])
def test_legacy_conflicts_report_counts_and_abort_without_repair(
        engine, monkeypatch, case, category):
    """Each preflight category reports its count and rolls back the entire DDL."""
    url = new_disposable_database(engine, "workout_conflict")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        cfg = alembic_config()
        cfg.attributes["disposable_test"] = True
        command.upgrade(cfg, "0002_master_records")
        db = database_engine(url)
        try:
            with db.begin() as c:
                if case == "bodyweight_kind":
                    # Earlier metadata allowed editing this default. The new
                    # backfill must report it, not create an invalid exercise.
                    c.exec_driver_sql("UPDATE exercise_categories SET measurement_kind='duration_distance' WHERE id=4")
                    legacy_fixture(c)
                elif case == "cancelled_pending":
                    legacy_fixture(c, cancelled=True)
                elif case == "invalid_target":
                    legacy_fixture(c, incomplete=True)
                else:
                    legacy_template_preflight_conflict(c, case)
            with db.connect() as c:
                before = capture_legacy_rows(c)
            with pytest.raises(RuntimeError, match=rf"{category}=1") as failure:
                command.upgrade(cfg, "head")
            assert "No legacy data was changed" in str(failure.value)
            with db.connect() as c:
                assert MigrationContext.configure(c).get_current_revision() == "0002_master_records"
                assert "measurement_kind" not in {col["name"] for col in sa.inspect(c).get_columns("exercises")}
                assert capture_legacy_rows(c) == before
        finally:
            db.dispose()


@pytest.mark.parametrize("case", ["timed", "cancelled"])
def test_downgrade_rejects_new_incompatible_history(engine, monkeypatch, case):
    """Disposable-only rollback still refuses data the earlier schema cannot hold."""
    url = new_disposable_database(engine, "workout_down")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        patch.setenv("USC_ALLOW_DISPOSABLE_DOWNGRADE", "1")
        cfg = alembic_config()
        cfg.attributes["disposable_test"] = True
        command.upgrade(cfg, "head")
        db = database_engine(url)
        try:
            with db.begin() as c:
                if case == "timed":
                    exercise(c, category=4, kind="duration")
                else:
                    owner, workout, _, _ = session(c)
                    save_cancelled_session(c, workout, owner)
            with pytest.raises(RuntimeError, match="conflicts"):
                command.downgrade(cfg, "0002_master_records")
            with db.connect() as c:
                assert MigrationContext.configure(c).get_current_revision() == "0003_workout_follow_up"
        finally:
            db.dispose()


def test_cancel_and_completion_serialize_without_rewriting_performance(engine):
    """Competing completion and cancellation either retain completion or reject it."""
    with engine.begin() as c:
        owner, workout, entry, st = session(c)
    def perform(action):
        """Run one independently committed operation in the concurrency race."""
        try:
            with engine.begin() as c:
                if action == "complete":
                    complete_set(c, st, owner, actual_reps=5)
                else:
                    save_cancelled_session(c, workout, owner)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(perform, ["complete", "cancel"]))
    assert outcomes[1] is True
    with engine.connect() as c:
        row = c.execute(sa.select(s.session_sets).where(s.session_sets.c.id == st)).mappings().one()
        assert row["status"] in ("completed", "cancelled")
        assert row["actual_reps"] == (5 if row["status"] == "completed" else None)
        assert c.execute(sa.select(s.workout_sessions.c.status).where(s.workout_sessions.c.id == workout)).scalar_one() == "cancelled"
