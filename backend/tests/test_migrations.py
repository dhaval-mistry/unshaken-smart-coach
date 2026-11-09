from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.db.config import describe_target
from app.db.migrate import ApprovalError, apply_upgrade, build_plan, current_revision
from tests.conftest import _psycopg_kwargs, migrate
from tests.helpers import ensure_lookups, make_user

EXPECTED_COLUMNS = {
    "users": "id display_name contact_email preferred_weight_unit status created_at updated_at",
    "user_identities": "id user_id provider issuer subject email_at_login email_verified last_login_at created_at",
    "exercise_categories": "id name sort_order is_active",
    "body_parts": "id name sort_order is_active",
    "exercises": "id name category_id body_part_id source_type description is_active created_at updated_at",
    "provider_exercises": "exercise_id provider_name provider_exercise_id provider_body_part provider_equipment "
                          "instructions target_muscles secondary_muscles media_references raw_payload "
                          "last_synced_at provider_updated_at",
    "custom_exercises": "exercise_id created_by_user_id",
    "workout_templates": "id owner_user_id template_type name notes copied_from_template_id version archived_at "
                         "created_at updated_at",
    "template_exercises": "id template_id exercise_id position notes",
    "template_sets": "id template_exercise_id set_number target_reps suggested_weight weight_unit rest_seconds",
    "workout_sessions": "id user_id source_template_id source_template_version name_snapshot status started_at "
                        "finished_at notes template_updated_at template_update_requested template_update_status "
                        "applied_template_id created_at updated_at",
    "session_exercises": "id session_id exercise_id source_template_exercise_id name_snapshot category_snapshot "
                         "body_part_snapshot position notes",
    "session_sets": "id session_exercise_id source_template_set_id set_number target_reps_snapshot "
                    "suggested_weight_snapshot suggested_weight_unit_snapshot actual_reps actual_weight weight_unit "
                    "status completed_at rest_seconds was_in_starting_plan removed_at rest_started_at "
                    "rest_ended_at created_at updated_at",
}

# (child table, fk column) -> ON DELETE action: r=restrict, c=cascade, n=set null
EXPECTED_FKS = {
    ("user_identities", "user_id"): "r", ("exercises", "category_id"): "r", ("exercises", "body_part_id"): "r",
    ("provider_exercises", "exercise_id"): "c", ("custom_exercises", "exercise_id"): "c",
    ("custom_exercises", "created_by_user_id"): "r", ("workout_templates", "owner_user_id"): "r",
    ("workout_templates", "copied_from_template_id"): "n", ("template_exercises", "template_id"): "c",
    ("template_exercises", "exercise_id"): "r", ("template_sets", "template_exercise_id"): "c",
    ("workout_sessions", "user_id"): "r", ("workout_sessions", "source_template_id"): "r",
    ("workout_sessions", "applied_template_id"): "r", ("session_exercises", "session_id"): "r",
    ("session_exercises", "exercise_id"): "r", ("session_exercises", "source_template_exercise_id"): "r",
    ("session_sets", "session_exercise_id"): "r", ("session_sets", "source_template_set_id"): "r",
}


def test_fresh_database_upgrades_to_head(migrated_url):
    engine = create_engine(migrated_url)
    with engine.connect() as conn:
        assert current_revision(conn) == "0001"
        assert conn.execute(text("SHOW server_version")).scalar_one().startswith("17.")
    engine.dispose()


def test_exactly_the_13_approved_tables_and_columns(db):
    rows = db.execute("SELECT table_name, column_name FROM information_schema.columns "
                      "WHERE table_schema='public' AND table_name <> 'alembic_version'").fetchall()
    actual: dict[str, set[str]] = {}
    for table, column in rows:
        actual.setdefault(table, set()).add(column)
    assert {t: set(c.split()) for t, c in EXPECTED_COLUMNS.items()} == actual
    assert len(actual) == 13


def test_foreign_keys_and_deletion_behaviour(db):
    rows = db.execute("""
        SELECT c.conrelid::regclass::text, a.attname, c.confdeltype
          FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
         WHERE c.contype='f' AND c.connamespace = 'public'::regnamespace""").fetchall()
    assert {(t, col): d for t, col, d in rows} == EXPECTED_FKS


def test_every_foreign_key_column_is_indexed(db):
    unindexed = db.execute("""
        SELECT c.conrelid::regclass::text, a.attname
          FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
         WHERE c.contype='f' AND NOT EXISTS (
               SELECT 1 FROM pg_index i WHERE i.indrelid=c.conrelid AND i.indkey[0]=c.conkey[1])""").fetchall()
    assert unindexed == []


def test_required_indexes_and_unique_keys_exist(db):
    names = {r[0] for r in db.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'")}
    for expected in ["ix_workout_templates_owner_archived", "ix_workout_sessions_user_started",
                     "ix_workout_sessions_user_status", "ix_exercises_lower_name_id",
                     "ix_custom_exercises_created_by_user_id", "ix_workout_sessions_applied_template",
                     "uq_user_identities_identity", "uq_provider_exercises_provider_key",
                     "uq_template_exercises_position", "uq_template_sets_number",
                     "uq_session_exercises_position", "uq_session_sets_number"]:
        assert expected in names


def test_rerun_at_latest_does_not_recreate_tables(migrated_url, db):
    ensure_lookups(db)
    user = make_user(db, "Survivor")
    oid_before = db.execute("SELECT oid FROM pg_class WHERE relname='users'").fetchone()[0]
    migrate(migrated_url)  # second run at head
    assert db.execute("SELECT oid FROM pg_class WHERE relname='users'").fetchone()[0] == oid_before
    assert db.execute("SELECT count(*) FROM users WHERE id=%s", (user,)).fetchone()[0] == 1
    assert "nothing to do" in apply_upgrade(migrated_url, describe_target(migrated_url))


def test_plan_shows_nonsecret_target_version_and_changes(make_disposable_db):
    url = make_disposable_db()
    plan = build_plan(url)
    assert f"Target database:  {url.database}" in plan
    assert "Target host:" in plan and "Target port:" in plan
    assert "Current version:  none" in plan and "0001" in plan
    if url.password:
        assert url.password not in plan
    assert "://" not in plan
    migrate(url)
    after = build_plan(url)
    assert "Current version:  0001" in after
    assert "already at the latest version" in after


def test_upgrade_requires_owner_approval_of_exact_target(make_disposable_db):
    url = make_disposable_db()
    for bad in (None, "", "localhost:5432/other_db", url.database):
        with pytest.raises(ApprovalError):
            apply_upgrade(url, bad)
    engine = create_engine(url)
    with engine.connect() as conn:  # nothing was applied
        assert current_revision(conn) is None
    engine.dispose()
    assert "0001" in apply_upgrade(url, describe_target(url))


def test_upgrade_preserves_existing_data_in_unrelated_tables(make_disposable_db):
    url = make_disposable_db()
    kw = _psycopg_kwargs(url, url.database)
    with psycopg.connect(**kw) as conn:
        conn.execute("CREATE TABLE keepme (v int)")
        conn.execute("INSERT INTO keepme VALUES (42)")
    apply_upgrade(url, describe_target(url))
    with psycopg.connect(**kw) as conn:
        assert conn.execute("SELECT v FROM keepme").fetchone()[0] == 42


def test_conflicting_existing_table_makes_upgrade_fail_without_data_loss(make_disposable_db):
    url = make_disposable_db()
    kw = _psycopg_kwargs(url, url.database)
    with psycopg.connect(**kw) as conn:
        conn.execute("CREATE TABLE users (legacy text)")
        conn.execute("INSERT INTO users VALUES ('keep')")
    assert "WARNING" in build_plan(url)
    with pytest.raises(Exception):
        apply_upgrade(url, describe_target(url))
    with psycopg.connect(**kw) as conn:
        assert conn.execute("SELECT legacy FROM users").fetchone()[0] == "keep"
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        assert tables == {"users"}  # transactional DDL: no partial schema left behind


def test_rollback_on_disposable_database_only(make_disposable_db):
    url = make_disposable_db()
    migrate(url)
    migrate(url, "base", down=True)
    with psycopg.connect(**_psycopg_kwargs(url, url.database)) as conn:
        left = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        funcs = conn.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace='public'::regnamespace "
            "AND (proname LIKE 'fn\\_%' OR proname LIKE 'trg\\_%')").fetchone()[0]
    assert left <= {"alembic_version"} and funcs == 0
    migrate(url)  # and it upgrades again cleanly
