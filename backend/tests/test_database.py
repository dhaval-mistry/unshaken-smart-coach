"""Real PostgreSQL integration checks; refuses non-disposable database targets."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext

from app.db.cli import alembic_config, migration_plan
from app.db.config import database_engine, database_url
from app.db.operations import complete_set, seal_starting_plan
from app.db import schema as s


@pytest.fixture(scope="session")
def engine():
    """Use only the independently created test target, never root development settings."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("Set TEST_DATABASE_URL to a fresh disposable PostgreSQL 17 database.")
    os.environ["DATABASE_URL"]=os.environ["TEST_DATABASE_URL"]
    url=database_url()
    if not url.database.startswith("unshaken_foundation_test_"):
        pytest.fail("Integration tests refuse this database name.")
    result=database_engine(url)
    with result.connect() as c:
        if c.exec_driver_sql("SELECT current_database()").scalar_one()!=url.database:
            pytest.fail("Unexpected database target.")
    yield result
    result.dispose()


def user(c):
    """Insert a synthetic owner with an explicit unit preference."""
    return c.execute(s.users.insert().values(display_name="Synthetic participant",preferred_weight_unit="kg",status="active").returning(s.users.c.id)).scalar_one()


def exercise(c, owner=None, category=1, kind=None):
    """Insert a matching exercise and source subtype atomically."""
    effective_kind = kind or c.execute(sa.select(s.exercise_categories.c.measurement_kind).where(s.exercise_categories.c.id==category)).scalar_one()
    identifier=c.execute(s.exercises.insert().values(name="Synthetic exercise",category_id=category,body_part_id=1,source_type="custom" if owner else "provider",measurement_kind=effective_kind).returning(s.exercises.c.id)).scalar_one()
    if owner:
        c.execute(s.custom_exercises.insert().values(exercise_id=identifier,created_by_user_id=owner))
    else:
        c.execute(s.provider_exercises.insert().values(exercise_id=identifier,provider_name="exercisedb",provider_exercise_id=str(uuid4()),last_synced_at=sa.func.now()))
    return identifier


def template(c, owner=None, exercise_id=None, category=1):
    """Create an ordered synthetic live plan and its one planned set."""
    identifier=c.execute(s.workout_templates.insert().values(name="Synthetic plan",template_type="personal" if owner else "sample",owner_user_id=owner).returning(s.workout_templates.c.id)).scalar_one()
    ex=exercise_id or exercise(c,category=category)
    entry=c.execute(s.template_exercises.insert().values(template_id=identifier,exercise_id=ex,position=1).returning(s.template_exercises.c.id)).scalar_one()
    kind=c.execute(sa.select(s.exercises.c.measurement_kind).where(s.exercises.c.id==ex)).scalar_one()
    targets={"target_reps":8} if kind=="reps" else {"target_duration_seconds":600}
    if kind=="duration_distance": targets["target_distance_meters"]="1500.000"
    planned=c.execute(s.template_sets.insert().values(template_exercise_id=entry,set_number=1,**targets).returning(s.template_sets.c.id)).scalar_one()
    return identifier,ex,entry,planned


def session(c, owner=None, ex=None, source=None, seal=True, category=1):
    """Capture real source rows into separate immutable initial plan and execution rows."""
    owner=owner or user(c)
    source_id,source_entry,source_set=(None,None,None)
    if source:
        source_id,ex,source_entry,source_set=source
    ex=ex or exercise(c,owner=owner,category=category)
    original=c.execute(sa.select(s.exercises,s.exercise_categories.c.name.label("category_name"),s.body_parts.c.name.label("body_name")).join(s.exercise_categories).join(s.body_parts).where(s.exercises.c.id==ex)).mappings().one()
    source_row=c.execute(sa.select(s.workout_templates).where(s.workout_templates.c.id==source_id)).mappings().one() if source_id else None
    w=c.execute(s.workout_sessions.insert().values(user_id=owner,name_snapshot="Synthetic workout",status="in_progress",
      source_template_id=source_id,source_template_id_snapshot=source_id,
      source_template_type_snapshot=source_row["template_type"] if source_row else None,
      source_template_version=source_row["version"] if source_row else None,
      template_update_status="pending" if source_id else "not_applicable").returning(s.workout_sessions.c.id)).scalar_one()
    e=c.execute(s.session_exercises.insert().values(session_id=w,exercise_id=ex,exercise_id_snapshot=ex,
      exercise_source_type_snapshot=original["source_type"],source_template_exercise_id=source_entry,
      source_template_exercise_id_snapshot=source_entry,name_snapshot=original["name"],category_snapshot=original["category_name"],
      body_part_snapshot=original["body_name"],measurement_kind_snapshot=original["measurement_kind"],position=1).returning(s.session_exercises.c.id)).scalar_one()
    targets={}
    if source_set:
        row=c.execute(sa.select(s.template_sets).where(s.template_sets.c.id==source_set)).mappings().one()
        for key in ("target_reps","target_duration_seconds","target_distance_meters","suggested_weight"):
            targets[key+"_snapshot"]=row[key]
        targets["suggested_weight_unit_snapshot"]=row["weight_unit"]
    st=c.execute(s.session_sets.insert().values(session_exercise_id=e,set_number=1,status="pending",was_in_starting_plan=True,
      source_template_set_id=source_set,source_template_set_id_snapshot=source_set,**targets).returning(s.session_sets.c.id)).scalar_one()
    if seal: seal_starting_plan(c,w)
    return owner,w,e,st


def rejects(engine, operation):
    """Include commit-time constraint failures, not only immediate row checks."""
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as c:
            operation(c)


def test_schema_and_seed_contract(engine):
    """Verify the published dictionary, keys, deletion actions, indexes and ordered seed values."""
    with engine.connect() as c:
        inspector=sa.inspect(c)
        assert set(inspector.get_table_names())==set(s.metadata.tables)|{"alembic_version"}
        assert sum(len(inspector.get_columns(t)) for t in s.metadata.tables)==129
        # The human-readable dictionary is an independent nullability contract.
        import re
        design=(Path(__file__).resolve().parents[2]/'docs/database/design.md').read_text(encoding='utf-8')
        for match in re.finditer(r'^### ([a-z_]+)\n\n\| Column[^\n]*\n\|[-|]+\n((?:\|[^\n]*\n)+)',design,re.M):
            actual={col['name']:col['nullable'] for col in inspector.get_columns(match[1])}
            for line in match[2].strip().splitlines():
                name,kind,rule=[part.strip() for part in line.split('|')[1:-1]]
                expected=rule.startswith(('Nullable','Physically nullable')) or (match[1],name) in {
                    ('workout_sessions','finished_at'),('session_sets','completed_at'),('session_sets','rest_started_at')}
                assert actual[name]==expected, (match[1],name,'dictionary nullability')
                reflected=next(col['type'] for col in inspector.get_columns(match[1]) if col['name']==name)
                if kind.startswith('VARCHAR'):
                    assert reflected.length==int(kind.split('(')[1][:-1])
                elif kind.startswith('NUMERIC'):
                    precision,scale=map(int,kind.split('(')[1][:-1].split(','))
                    assert (reflected.precision,reflected.scale)==(precision,scale)
                elif kind=='TIMESTAMPTZ':
                    assert reflected.timezone is True
                else:
                    assert str(reflected)==kind
        for table in s.metadata.sorted_tables:
            assert [x["name"] for x in inspector.get_columns(table.name)]==list(table.columns.keys())
            assert inspector.get_pk_constraint(table.name)["constrained_columns"]==[x.name for x in table.primary_key]
            actual={tuple(fk["constrained_columns"]):fk["options"].get("ondelete") for fk in inspector.get_foreign_keys(table.name)}
            for col in table.columns:
                for fk in col.foreign_keys:
                    assert actual[(col.name,)]==fk.ondelete
            actual_indexes={i["name"] for i in inspector.get_indexes(table.name)}
            assert {i.name for i in table.indexes}<=actual_indexes
            assert {i.name for i in table.constraints if isinstance(i,sa.CheckConstraint)} <= {
                i["name"] for i in inspector.get_check_constraints(table.name)}
        assert MigrationContext.configure(c).get_current_revision()=="0003_workout_follow_up"
        cats=c.execute(sa.select(s.exercise_categories).order_by(s.exercise_categories.c.sort_order)).mappings().all()
        assert [x["name"] for x in cats]==["Barbell","Dumbbell","Machine/Other","Bodyweight","Assisted Bodyweight","Reps Only","Cardio","Duration"]
        assert [x["id"] for x in cats]==list(range(1,9))
        assert [x["measurement_kind"] for x in cats]==["reps"]*6+["duration_distance","duration"]
        parts=c.execute(sa.select(s.body_parts).order_by(s.body_parts.c.sort_order)).mappings().all()
        assert [x["name"] for x in parts]==["None","Arms","Back","Cardio","Chest","Core","Full Body","Legs","Olympic","Other","Shoulders"]
        assert all(x["is_active"] for x in [*cats,*parts])


@pytest.mark.parametrize("category,actuals",[(1,{"actual_reps":8}),(7,{"actual_duration_seconds":600,"actual_distance_meters":"1500"}),(8,{"actual_duration_seconds":30})])
def test_measurements_atomic_rest_and_retry(engine,category,actuals):
    """All three modes complete without required weight and retry preserves actuals/timer."""
    with engine.begin() as c:
        owner,w,e,st=session(c,category=category)
        first=complete_set(c,st,owner,**actuals)
        repeated=complete_set(c,st,owner,actual_reps=999)
        assert first==repeated
        assert first["completed_at"]==first["rest_started_at"]
        assert first["rest_seconds"]==120
        assert first["actual_weight"] is None


@pytest.mark.parametrize("category,actuals",[(1,{}),(1,{"actual_reps":0}),(1,{"actual_duration_seconds":5}),
 (7,{"actual_duration_seconds":10}),(7,{"actual_distance_meters":10}),(7,{"actual_reps":1,"actual_duration_seconds":10,"actual_distance_meters":10}),
 (8,{"actual_reps":1,"actual_duration_seconds":10}),(8,{"actual_duration_seconds":-1})])
def test_invalid_measurements(engine,category,actuals):
    """Missing, wrong-mode, zero and negative actual values fail at row/commit boundaries."""
    def operation(c):
        owner,w,e,st=session(c,category=category)
        complete_set(c,st,owner,**actuals)
    rejects(engine,operation)


@pytest.mark.parametrize("weight,unit",[(None,"kg"),(1,None),(1,"oz"),(-1,"kg"),("NaN","kg")])
def test_weight_pairs_invalid(engine,weight,unit):
    """Missing unit/value, unsupported units, negative and nonfinite weight are rejected."""
    def operation(c):
        owner,w,e,st=session(c)
        complete_set(c,st,owner,actual_reps=4,actual_weight=weight,weight_unit=unit)
    rejects(engine,operation)


def test_zero_weight_is_explicit_and_optional_units(engine):
    """Zero is retained as a supplied value rather than treated as missing."""
    with engine.begin() as c:
        owner,w,e,st=session(c)
        result=complete_set(c,st,owner,actual_reps=2,actual_weight=0,weight_unit="kg")
        assert result["actual_weight"]==0 and result["weight_unit"]=="kg"


@pytest.mark.parametrize("case",["missing","wrong","both"])
def test_exact_source_subtype(engine,case):
    """Subtype guards run at transaction end and reject missing, wrong and duplicate subtypes."""
    def operation(c):
        u=user(c)
        ex=c.execute(s.exercises.insert().values(name="Invalid source",source_type="provider",category_id=1,body_part_id=1,measurement_kind="reps").returning(s.exercises.c.id)).scalar_one()
        if case in ("wrong","both"): c.execute(s.custom_exercises.insert().values(exercise_id=ex,created_by_user_id=u))
        if case=="both": c.execute(s.provider_exercises.insert().values(exercise_id=ex,provider_name="exercisedb",provider_exercise_id=str(uuid4()),last_synced_at=sa.func.now()))
    rejects(engine,operation)


@pytest.mark.parametrize("case",["template","sample","session","owner_edit","source_edit"])
def test_ownership_and_parent_changes(engine,case):
    """Check direct attachment and later parent edits, not just unguessable IDs."""
    def operation(c):
        a,b=user(c),user(c)
        ex=exercise(c,owner=a)
        if case=="template": template(c,owner=b,exercise_id=ex)
        elif case=="sample": template(c,exercise_id=ex)
        elif case=="session": session(c,owner=b,ex=ex)
        else:
            template(c,owner=a,exercise_id=ex)
            if case=="owner_edit": c.execute(s.custom_exercises.update().where(s.custom_exercises.c.exercise_id==ex).values(created_by_user_id=b))
            else: c.execute(s.exercises.update().where(s.exercises.c.id==ex).values(source_type="provider"))
    rejects(engine,operation)


def test_unsealed_and_malformed_capture(engine):
    """A half-capture cannot commit; malformed/reordered/extra/missing JSON cannot be sealed."""
    rejects(engine,lambda c:session(c,seal=False))
    for mode in ("empty","unknown","wrong_type","missing","changed_target"):
        def operation(c):
            owner,w,e,st=session(c,seal=False)
            snap=c.execute(sa.text("SELECT usc_snapshot(to_jsonb(w)) FROM workout_sessions w WHERE id=:id"),{"id":w}).scalar_one()
            if mode=="empty": snap["exercises"]=[]
            if mode=="unknown": snap["unknown"]=1
            if mode=="wrong_type": snap["exercises"][0]["position"]="1"
            if mode=="missing": del snap["exercises"][0]["sets"][0]["target_reps"]
            if mode=="changed_target": snap["exercises"][0]["sets"][0]["target_reps"]=100
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(starting_plan_snapshot=snap))
        rejects(engine,operation)


def test_permanent_source_and_unperformed_removal_preserve_start(engine):
    """Delete live plan/catalog/unused execution rows without losing initial targets or UUIDs."""
    with engine.begin() as c:
        owner=user(c)
        plan=template(c,owner=owner,category=7)
        owner,w,e,st=session(c,owner=owner,source=plan)
        original=c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot).where(s.workout_sessions.c.id==w)).scalar_one()
        c.execute(s.session_sets.delete().where(s.session_sets.c.id==st))
        c.execute(s.workout_templates.delete().where(s.workout_templates.c.id==plan[0]))
        c.execute(s.exercises.delete().where(s.exercises.c.id==plan[1]))
        row=c.execute(sa.select(s.workout_sessions).where(s.workout_sessions.c.id==w)).mappings().one()
        assert row["starting_plan_snapshot"]==original and row["source_template_id"] is None
        assert row["source_template_id_snapshot"]==plan[0]
        assert original["exercises"][0]["sets"][0]["target_distance_meters"]=="1500.000"


@pytest.mark.parametrize("kind",["source_id_reuse","initial_id_reuse","initial_number_reuse","snapshot_edit","live_detach"])
def test_historical_identity_and_detachment(engine,kind):
    """Historical UUIDs cannot be forged, reattached or used to recreate an initial row."""
    def operation(c):
        owner=user(c); plan=template(c,owner=owner)
        owner,w,e,st=session(c,owner=owner,source=plan)
        if kind=="snapshot_edit":
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(starting_plan_snapshot={}))
        elif kind=="live_detach":
            c.execute(s.session_exercises.update().where(s.session_exercises.c.id==e).values(exercise_id=None))
        else:
            c.execute(s.session_sets.delete().where(s.session_sets.c.id==st))
            if kind=="source_id_reuse":
                c.execute(s.workout_templates.delete().where(s.workout_templates.c.id==plan[0]))
                c.execute(s.workout_templates.insert().values(id=plan[0],name="Impersonation",template_type="personal",owner_user_id=owner))
            else:
                c.execute(s.session_sets.insert().values(id=st if kind=="initial_id_reuse" else uuid4(),session_exercise_id=e,set_number=1,status="pending",was_in_starting_plan=False))
    rejects(engine,operation)


@pytest.mark.parametrize("case",["set_delete","rewind","actual_edit","parent_delete","exercise_parent_delete","timestamp_edit"])
def test_completed_history_guards(engine,case):
    """Protect completed actuals and parents including attempts to rewind then delete."""
    def operation(c):
        owner,w,e,st=session(c); complete_set(c,st,owner,actual_reps=8)
        if case=="set_delete": c.execute(s.session_sets.delete().where(s.session_sets.c.id==st))
        elif case=="rewind": c.execute(s.session_sets.update().where(s.session_sets.c.id==st).values(status="pending",completed_at=None,rest_started_at=None))
        elif case=="actual_edit": c.execute(s.session_sets.update().where(s.session_sets.c.id==st).values(actual_reps=20))
        elif case=="parent_delete": c.execute(s.workout_sessions.delete().where(s.workout_sessions.c.id==w))
        elif case=="exercise_parent_delete": c.execute(s.session_exercises.delete().where(s.session_exercises.c.id==e))
        else: c.execute(s.session_sets.update().where(s.session_sets.c.id==st).values(completed_at=sa.func.now()))
    rejects(engine,operation)


@pytest.mark.parametrize("case",["terminal_missing_time","early_set","late_finish","rest_end","terminal_rewind"])
def test_chronology_and_terminal_rules(engine,case):
    """Validate both row-local timestamps and the parent session chronology."""
    def operation(c):
        owner,w,e,st=session(c)
        started=c.execute(sa.select(s.workout_sessions.c.started_at).where(s.workout_sessions.c.id==w)).scalar_one()
        if case=="terminal_missing_time": c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed"))
        elif case=="early_set": c.execute(s.session_sets.update().where(s.session_sets.c.id==st).values(status="completed",actual_reps=1,completed_at=started-timedelta(seconds=1),rest_started_at=started-timedelta(seconds=1)))
        else:
            complete_set(c,st,owner,actual_reps=1)
            if case=="rest_end": c.execute(s.session_sets.update().where(s.session_sets.c.id==st).values(rest_ended_at=started-timedelta(seconds=1)))
            elif case=="late_finish": c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=started))
            else:
                c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp()))
                c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="in_progress",finished_at=None))
    rejects(engine,operation)


def test_one_active_concurrency_and_release(engine):
    """Competing transactions cannot reserve two active slots; terminal status releases it."""
    with engine.begin() as c: owner=user(c)
    def start():
        try:
            with engine.begin() as c: return session(c,owner=owner)[1]
        except sa.exc.IntegrityError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda _:start(),range(2)))
    assert sum(x is not None for x in ids)==1
    with engine.begin() as c:
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==next(x for x in ids if x)).values(status="completed",finished_at=sa.func.clock_timestamp()))
        session(c,owner=owner)


def test_plan_and_repeat_upgrade_are_read_only_at_head(engine):
    """No migration/seed recreation at head and stale approval tokens fail."""
    with engine.connect() as c:
        details,token=migration_plan(c,database_url())
        assert details["current_revision"]=="0003_workout_follow_up" and details["planned_migrations"]==[]
        count=c.execute(sa.select(sa.func.count()).select_from(s.exercise_categories)).scalar_one()
    config=alembic_config()
    config.attributes["disposable_test"]=True
    command.upgrade(config,"head")
    with engine.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(s.exercise_categories)).scalar_one()==count


def test_timestamp_server_maintenance(engine):
    """Ignore caller-supplied modification time and reject edits to creation time."""
    with engine.begin() as c:
        owner=user(c)
        before=c.execute(sa.select(s.users).where(s.users.c.id==owner)).mappings().one()
        c.execute(s.users.update().where(s.users.c.id==owner).values(display_name="Updated synthetic participant",updated_at=datetime(2000,1,1,tzinfo=timezone.utc)))
        after=c.execute(sa.select(s.users).where(s.users.c.id==owner)).mappings().one()
        assert after["created_at"]==before["created_at"] and after["updated_at"]>=before["updated_at"]
    rejects(engine,lambda c:c.execute(s.users.update().where(s.users.c.id==owner).values(created_at=datetime(2000,1,1,tzinfo=timezone.utc))))


def new_disposable_database(engine, suffix):
    """Create another isolated test database for lifecycle cases with no application rows."""
    name="unshaken_foundation_test_"+suffix+"_"+uuid4().hex[:8]
    assert name.startswith("unshaken_foundation_test_")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql("CREATE DATABASE "+c.dialect.identifier_preparer.quote(name))
    return database_url().set(database=name)


def test_fresh_downgrade_upgrade_and_seed_conflict(engine,monkeypatch):
    """Rollback fresh disposable data; conflicts leave custom data/revision unchanged."""
    url=new_disposable_database(engine,"rollback")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL",url.render_as_string(hide_password=False))
        cfg=alembic_config()
        cfg.attributes["disposable_test"]=True
        command.upgrade(cfg,"head")
        command.check(cfg)
        with pytest.raises(RuntimeError,match="disposable"):
            patch.delenv("USC_ALLOW_DISPOSABLE_DOWNGRADE",raising=False)
            command.downgrade(cfg,"base")
        patch.setenv("USC_ALLOW_DISPOSABLE_DOWNGRADE","1")
        command.downgrade(cfg,"base")
        with database_engine(url).connect() as c:
            assert set(sa.inspect(c).get_table_names())=={"alembic_version"}
        command.upgrade(cfg,"head")
        with database_engine(url).connect() as c:
            assert c.exec_driver_sql("SELECT count(*) FROM body_parts").scalar_one()==11
    url=new_disposable_database(engine,"conflict")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL",url.render_as_string(hide_password=False))
        cfg=alembic_config(); cfg.attributes["disposable_test"]=True
        command.upgrade(cfg,"0001_database_foundation")
        with database_engine(url).begin() as c:
            c.exec_driver_sql("INSERT INTO body_parts(id,name,sort_order,is_active) VALUES (1,'Custom retained choice',1,true)")
        with pytest.raises(RuntimeError,match="conflict"):
            command.upgrade(cfg,"head")
        with database_engine(url).connect() as c:
            assert c.exec_driver_sql("SELECT name FROM body_parts WHERE id=1").scalar_one()=="Custom retained choice"
            assert c.exec_driver_sql("SELECT count(*) FROM exercise_categories").scalar_one()==0
            assert MigrationContext.configure(c).get_current_revision()=="0001_database_foundation"


@pytest.mark.parametrize("case",["entry","set","orphan_session","orphan_copy"])
def test_source_lineage_is_not_merely_a_uuid(engine,case):
    """Reject another plan's entries/sets and fabricated original-only identities."""
    def operation(c):
        owner=user(c); a=template(c,owner=owner); b=template(c,owner=owner)
        if case=="entry": session(c,owner=owner,source=(a[0],a[1],b[2],a[3]))
        elif case=="set": session(c,owner=owner,source=(a[0],a[1],a[2],b[3]))
        elif case=="orphan_copy": c.execute(s.workout_templates.insert().values(name="Forged copy",owner_user_id=owner,template_type="personal",copied_from_template_id_snapshot=uuid4()))
        else: c.execute(s.workout_sessions.insert().values(user_id=owner,name_snapshot="Forged session",status="in_progress",source_template_id_snapshot=uuid4(),source_template_type_snapshot="personal",source_template_version=1,template_update_status="pending"))
    rejects(engine,operation)


def test_saved_performance_survives_source_deletion(engine):
    """Completed values and starting evidence survive real catalog/template deletion."""
    with engine.begin() as c:
        owner=user(c); plan=template(c,owner=owner)
        owner,w,e,st=session(c,owner=owner,source=plan)
        complete_set(c,st,owner,actual_reps=9,actual_weight=0,weight_unit="lb")
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp(),template_update_requested=False,template_update_status="declined"))
        original=c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot).where(s.workout_sessions.c.id==w)).scalar_one()
        c.execute(s.workout_templates.delete().where(s.workout_templates.c.id==plan[0]))
        c.execute(s.exercises.delete().where(s.exercises.c.id==plan[1]))
        row=c.execute(sa.select(s.session_sets).where(s.session_sets.c.id==st)).mappings().one()
        assert row["actual_reps"]==9 and row["actual_weight"]==0 and row["source_template_set_id"] is None
        assert row["source_template_set_id_snapshot"]==plan[3]
        assert c.execute(sa.select(s.workout_sessions.c.starting_plan_snapshot).where(s.workout_sessions.c.id==w)).scalar_one()==original


def test_apply_copy_outcome_survives_target_deletion(engine):
    """A valid sample-copy result persists after both its target/source are removed."""
    from app.db.operations import locked_template_update
    with engine.begin() as c:
        owner=user(c); plan=template(c)
        owner,w,e,st=session(c,owner=owner,source=plan)
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp(),template_update_requested=True))
        with locked_template_update(c,w,owner):
            target=c.execute(s.workout_templates.insert().values(name="Synthetic personal copy",owner_user_id=owner,template_type="personal",copied_from_template_id=plan[0],copied_from_template_id_snapshot=plan[0]).returning(s.workout_templates.c.id)).scalar_one()
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(template_update_status="applied",applied_template_id=target,applied_template_id_snapshot=target,template_updated_at=sa.func.clock_timestamp()))
        c.execute(s.workout_templates.delete().where(s.workout_templates.c.id.in_([target,plan[0]])))
        row=c.execute(sa.select(s.workout_sessions).where(s.workout_sessions.c.id==w)).mappings().one()
        assert row["template_update_status"]=="applied" and row["applied_template_id"] is None
        assert row["applied_template_id_snapshot"]==target and row["source_template_id_snapshot"]==plan[0]


def test_template_version_preflight_requires_recorded_version(engine):
    """The service primitive detects a changed version before any mapping operation."""
    from app.db.operations import locked_template_update
    with engine.begin() as c:
        owner=user(c); plan=template(c,owner=owner)
        owner,w,e,st=session(c,owner=owner,source=plan)
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp(),template_update_requested=True))
        c.execute(s.workout_templates.update().where(s.workout_templates.c.id==plan[0]).values(version=2))
        with pytest.raises(ValueError,match="version"):
            with locked_template_update(c,w,owner):
                pytest.fail("Changed source was allowed to enter optional mapping.")


def test_master_rename_does_not_change_captured_mode(engine):
    """Captured Cardio remains duration+distance after an editable display-name change."""
    with engine.connect() as c:
        transaction=c.begin()
        try:
            owner,w,e,st=session(c,category=7)
            c.execute(s.exercise_categories.update().where(s.exercise_categories.c.id==7).values(name="Renamed cardio choice"))
            result=complete_set(c,st,owner,actual_duration_seconds=20,actual_distance_meters=50)
            c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            assert result["actual_reps"] is None
        finally: transaction.rollback()


@pytest.mark.parametrize("case",["wrong_owner","wrong_copy_source","missing_target","finish_without_choice"])
def test_optional_update_ownership_and_choice(engine,case):
    """Applied results require a real authorized target/source and an explicit finish answer."""
    def operation(c):
        owner=user(c); plan=template(c)
        owner,w,e,st=session(c,owner=owner,source=plan)
        if case=="finish_without_choice":
            c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp()))
            return
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp(),template_update_requested=True))
        target=uuid4()
        if case!="missing_target":
            target=c.execute(s.workout_templates.insert().values(name="Invalid optional target",template_type="personal",owner_user_id=user(c) if case=="wrong_owner" else owner).returning(s.workout_templates.c.id)).scalar_one()
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(template_update_status="applied",applied_template_id=target,applied_template_id_snapshot=target,template_updated_at=sa.func.clock_timestamp()))
    rejects(engine,operation)


@pytest.mark.parametrize("field,value",[("suggested_weight",2),("weight_unit","kg"),("target_reps",0),("target_duration_seconds",5)])
def test_template_measurement_and_weight_guards(engine,field,value):
    """Planned measurements/unit pairs are enforced independently of actual values."""
    def operation(c):
        owner=user(c); plan=template(c,owner=owner)
        c.execute(s.template_sets.update().where(s.template_sets.c.id==plan[3]).values(**{field:value}))
    rejects(engine,operation)


def test_completed_history_survives_failed_optional_transaction(engine):
    """A rolled-back optional update cannot roll back an already committed workout."""
    from app.db.operations import locked_template_update
    with engine.begin() as c:
        owner=user(c); plan=template(c,owner=owner)
        owner,w,e,st=session(c,owner=owner,source=plan)
        complete_set(c,st,owner,actual_reps=7)
        c.execute(s.workout_sessions.update().where(s.workout_sessions.c.id==w).values(status="completed",finished_at=sa.func.clock_timestamp(),template_update_requested=True))
    with pytest.raises(RuntimeError,match="Synthetic"):
        with engine.begin() as c:
            with locked_template_update(c,w,owner):
                c.execute(s.workout_templates.update().where(s.workout_templates.c.id==plan[0]).values(name="Rolled back optional edit",version=2))
                raise RuntimeError("Synthetic optional failure")
    with engine.connect() as c:
        row=c.execute(sa.select(s.workout_sessions).where(s.workout_sessions.c.id==w)).mappings().one()
        assert row["status"]=="completed" and row["template_update_status"]=="pending"
        assert c.execute(sa.select(s.session_sets.c.actual_reps).where(s.session_sets.c.id==st)).scalar_one()==7
        assert c.execute(sa.select(s.workout_templates.c.version).where(s.workout_templates.c.id==plan[0])).scalar_one()==1


def test_concurrent_completion_returns_original_event(engine):
    """Two competing completion calls return one saved result and one timer start."""
    with engine.begin() as c: owner,w,e,st=session(c)
    def finish(reps):
        """Complete in a separate transaction and return its saved event record."""
        with engine.begin() as c: return complete_set(c,st,owner,actual_reps=reps)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first,second=list(pool.map(finish,[6,12]))
    assert first==second and first["actual_reps"] in (6,12)


def test_existing_matching_seeds_and_unrelated_records_are_preserved(engine,monkeypatch):
    """Versioned seeding preserves custom rows and accepts exact matching seed identities."""
    url=new_disposable_database(engine,"preserve")
    with monkeypatch.context() as patch:
        patch.setenv("DATABASE_URL",url.render_as_string(hide_password=False))
        cfg=alembic_config(); cfg.attributes["disposable_test"]=True
        command.upgrade(cfg,"0001_database_foundation")
        with database_engine(url).begin() as c:
            c.exec_driver_sql("INSERT INTO body_parts(id,name,sort_order,is_active) VALUES (1,'None',1,true),(99,'Unrelated retained choice',99,true)")
        command.upgrade(cfg,"head"); command.upgrade(cfg,"head")
        with database_engine(url).connect() as c:
            assert c.exec_driver_sql("SELECT name FROM body_parts WHERE id=99").scalar_one()=="Unrelated retained choice"
            assert c.exec_driver_sql("SELECT count(*) FROM body_parts").scalar_one()==12
            assert c.exec_driver_sql("SELECT count(*) FROM exercise_categories").scalar_one()==8


def test_cli_target_confirmation_and_safe_errors(engine):
    """Only the exact current target/revision token can authorize an upgrade."""
    import subprocess
    import sys
    with engine.connect() as c:
        details,token=migration_plan(c,database_url())
    base=[sys.executable,"-m","app.db.cli"]
    rejected=subprocess.run(base+["upgrade","--approve-target","wrong-token"],capture_output=True,text=True)
    assert rejected.returncode==2 and "No migrations applied" in rejected.stdout
    accepted=subprocess.run(base+["upgrade","--approve-target",token],capture_output=True,text=True)
    assert accepted.returncode==0 and "Already at head" in accepted.stdout
    environment=dict(os.environ,DATABASE_URL="invalid SECRET_SENTINEL setting")
    failed=subprocess.run(base+["plan"],env=environment,capture_output=True,text=True)
    assert failed.returncode==1 and "SECRET_SENTINEL" not in failed.stdout+failed.stderr


def test_truncate_cannot_bypass_history_guards(engine):
    """Even a writer with TRUNCATE privilege cannot accidentally bypass row-delete guards."""
    rejects(engine,lambda c:c.exec_driver_sql("TRUNCATE workout_sessions CASCADE"))


@pytest.mark.parametrize("column",["category_id","body_part_id"])
def test_invalid_master_reference_is_rejected(engine,column):
    """A nonexistent master key fails the real FK rather than a later subtype check."""
    with pytest.raises(sa.exc.IntegrityError) as error:
        with engine.begin() as c:
            ex=exercise(c)
            c.execute(s.exercises.update().where(s.exercises.c.id==ex).values(**{column:32000}))
    assert error.value.orig.sqlstate=="23503"


@pytest.mark.parametrize("column,value",[("instructions",[12]),("target_muscles",["valid",12]),("raw_payload",[])])
def test_provider_json_shapes(engine,column,value):
    """Provider metadata is typed data, not arbitrary arrays or scalar payloads."""
    def operation(c):
        ex=exercise(c)
        c.execute(s.provider_exercises.update().where(s.provider_exercises.c.exercise_id==ex).values(**{column:value}))
    rejects(engine,operation)
