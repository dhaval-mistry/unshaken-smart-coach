"""Invalid records are rejected by the database itself (SQLSTATE in comments)."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import errors

from tests.helpers import (T0, ensure_lookups, make_custom_exercise, make_provider_exercise, make_session,
                           make_session_exercise, make_session_set, make_template, make_template_exercise,
                           make_template_set, make_user, minutes, one)


@pytest.fixture(autouse=True)
def lookups(db):
    ensure_lookups(db)


def rejected(db, error, sql, *params):
    """Run one statement in its own transaction; it must raise `error`."""
    with pytest.raises(error):
        with db.transaction():
            db.execute(sql, params)


# ---- relationships -------------------------------------------------------

def test_foreign_keys_reject_missing_parents(db):
    rejected(db, errors.ForeignKeyViolation,
             "INSERT INTO user_identities (user_id, provider, issuer, subject) VALUES (%s,'google','i','s')", uuid.uuid4())
    rejected(db, errors.ForeignKeyViolation,
             "INSERT INTO exercises (name, category_id, body_part_id, source_type) VALUES ('X',99,5,'provider')")
    rejected(db, errors.ForeignKeyViolation,
             "INSERT INTO template_exercises (template_id, exercise_id, position) VALUES (%s,%s,1)", uuid.uuid4(), uuid.uuid4())


def test_exercise_needs_exactly_one_matching_detail_row(db):
    # No detail row at all.
    rejected(db, errors.CheckViolation,
             "INSERT INTO exercises (name, category_id, body_part_id, source_type) VALUES ('Orphan',1,5,'provider')")
    # Provider exercise carrying a custom detail row (source_type mismatch).
    owner = make_user(db)
    ex = make_provider_exercise(db, "Mismatch")
    rejected(db, errors.CheckViolation,
             "INSERT INTO custom_exercises (exercise_id, created_by_user_id) VALUES (%s,%s)", ex, owner)
    # Custom exercise with both detail rows.
    cx = make_custom_exercise(db, owner, "Both")
    rejected(db, errors.CheckViolation,
             "INSERT INTO provider_exercises (exercise_id, provider_name, provider_exercise_id, last_synced_at) "
             "VALUES (%s,'exercisedb','dup',now())", cx)


def test_provider_json_shapes_and_unique_provider_key(db):
    ex = make_provider_exercise(db, "Json")
    rejected(db, errors.CheckViolation,
             "UPDATE provider_exercises SET instructions = '{\"a\":1}'::jsonb WHERE exercise_id=%s", ex)
    pk = one(db, "SELECT provider_exercise_id FROM provider_exercises WHERE exercise_id=%s", ex)
    other = make_provider_exercise(db, "Json2")
    rejected(db, errors.UniqueViolation,
             "UPDATE provider_exercises SET provider_exercise_id=%s WHERE exercise_id=%s", pk, other)


def test_template_ownership_type_consistency(db):
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_templates (template_type, name) VALUES ('personal','No owner')")
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_templates (owner_user_id, template_type, name) VALUES (%s,'sample','Owned')", make_user(db))


# ---- another user's private exercises -------------------------------------

def test_other_users_private_exercise_rejected_in_template(db):
    alice, bob = make_user(db, "Alice"), make_user(db, "Bob")
    alices_lift = make_custom_exercise(db, alice, "Alice only")
    bobs_plan = make_template(db, bob)
    with pytest.raises(errors.CheckViolation):
        make_template_exercise(db, bobs_plan, alices_lift)
    # The owner may use it.
    make_template_exercise(db, make_template(db, alice), alices_lift)


def test_private_exercise_rejected_in_shared_sample(db):
    alice = make_user(db)
    lift = make_custom_exercise(db, alice, "Private")
    with pytest.raises(errors.CheckViolation):
        make_template_exercise(db, make_template(db, None, "Sample"), lift)
    make_template_exercise(db, make_template(db, None, "Sample ok"), make_provider_exercise(db, "Public"))


def test_other_users_private_exercise_rejected_in_session(db):
    alice, bob = make_user(db, "Alice"), make_user(db, "Bob")
    lift = make_custom_exercise(db, alice, "Alice only 2")
    with pytest.raises(errors.CheckViolation):
        make_session_exercise(db, make_session(db, bob), lift)
    make_session_exercise(db, make_session(db, alice), lift)


def test_changing_ownership_later_cannot_expose_private_exercise(db):
    alice, bob = make_user(db, "Alice"), make_user(db, "Bob")
    lift = make_custom_exercise(db, alice, "Handoff")
    plan = make_template(db, alice)
    make_template_exercise(db, plan, lift)
    rejected(db, errors.CheckViolation, "UPDATE workout_templates SET owner_user_id=%s WHERE id=%s", bob, plan)
    rejected(db, errors.CheckViolation,
             "UPDATE custom_exercises SET created_by_user_id=%s WHERE exercise_id=%s", bob, lift)


# ---- incorrect source links ----------------------------------------------

def _templated_session(db):
    user = make_user(db)
    ex = make_provider_exercise(db, "Squat")
    plan = make_template(db, user)
    te = make_template_exercise(db, plan, ex)
    ts = make_template_set(db, te)
    session = make_session(db, user, plan, 1)
    return user, ex, plan, te, ts, session


def test_session_exercise_source_must_belong_to_session_template_and_exercise(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    make_session_exercise(db, session, ex, te)  # correct link accepted
    other_plan = make_template(db, user, "Other")
    other_te = make_template_exercise(db, other_plan, ex)
    with pytest.raises(errors.CheckViolation):  # template exercise from a different template
        make_session_exercise(db, session, ex, other_te, position=2)
    other_ex = make_provider_exercise(db, "Deadlift")
    with pytest.raises(errors.CheckViolation):  # same template, different exercise
        make_session_exercise(db, session, other_ex, te, position=3)
    adhoc = make_session(db, user, status="completed", finished=minutes(30))  # one in-progress per user
    with pytest.raises(errors.CheckViolation):  # ad hoc session cannot claim a template link
        make_session_exercise(db, adhoc, ex, te)


def test_session_set_source_must_belong_to_session_exercise_source(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    se = make_session_exercise(db, session, ex, te)
    make_session_set(db, se, 1, ts)  # correct
    te2 = make_template_exercise(db, plan, make_provider_exercise(db, "Row"), 2)
    ts2 = make_template_set(db, te2)
    with pytest.raises(errors.CheckViolation):
        make_session_set(db, se, 2, ts2)


def test_added_set_cannot_claim_starting_plan_lineage(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    se = make_session_exercise(db, session, ex, te)
    rejected(db, errors.CheckViolation,
             "INSERT INTO session_sets (session_exercise_id, source_template_set_id, set_number, status, was_in_starting_plan) "
             "VALUES (%s,%s,5,'pending',false)", se, ts)


def test_applied_template_must_be_owned_copy_or_source(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    stranger = make_user(db, "Stranger")
    theirs = make_template(db, stranger, "Theirs")
    rejected(db, errors.CheckViolation,
             "UPDATE workout_sessions SET status='completed', finished_at=%s, template_update_requested=true, "
             "template_update_status='applied', applied_template_id=%s, template_updated_at=%s WHERE id=%s",
             minutes(60), theirs, minutes(61), session)
    rejected(db, errors.CheckViolation,  # pending cannot carry an applied target
             "UPDATE workout_sessions SET applied_template_id=%s WHERE id=%s", plan, session)
    db.execute("UPDATE workout_sessions SET status='completed', finished_at=%s, template_update_requested=true, "
               "template_update_status='applied', applied_template_id=%s, template_updated_at=%s WHERE id=%s",
               (minutes(60), plan, minutes(61), session))  # personal source is its own target


def test_sample_source_yes_requires_personal_copy_of_that_sample(db):
    user = make_user(db)
    sample = make_template(db, None, "Sample")
    session = make_session(db, user, sample, 1)
    unrelated = make_template(db, user, "Unrelated personal")
    args = (minutes(60), unrelated, minutes(61), session)
    sql = ("UPDATE workout_sessions SET status='completed', finished_at=%s, template_update_requested=true, "
           "template_update_status='applied', applied_template_id=%s, template_updated_at=%s WHERE id=%s")
    rejected(db, errors.CheckViolation, sql, *args)
    copy = one(db, "INSERT INTO workout_templates (owner_user_id, template_type, name, copied_from_template_id) "
                   "VALUES (%s,'personal','Copy',%s) RETURNING id", user, sample)
    db.execute(sql, (minutes(60), copy, minutes(61), session))


# ---- weight / unit --------------------------------------------------------

def test_invalid_weight_unit_combinations_rejected(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    se = make_session_exercise(db, session, ex, te)
    insert_ts = ("INSERT INTO template_sets (template_exercise_id, set_number, suggested_weight, weight_unit) "
                 "VALUES (%s,%s,%s,%s)")
    rejected(db, errors.CheckViolation, insert_ts, te, 9, 20, None)       # weight without unit
    rejected(db, errors.CheckViolation, insert_ts, te, 9, None, "kg")     # unit without weight
    rejected(db, errors.CheckViolation, insert_ts, te, 9, 20, "st")       # unknown unit
    rejected(db, errors.CheckViolation, insert_ts, te, 9, -1, "kg")       # negative weight
    insert_ss = ("INSERT INTO session_sets (session_exercise_id, set_number, status, was_in_starting_plan, "
                 "actual_weight, weight_unit) VALUES (%s,%s,'pending',false,%s,%s)")
    rejected(db, errors.CheckViolation, insert_ss, se, 9, 20, None)
    rejected(db, errors.CheckViolation, insert_ss, se, 9, None, "lb")
    rejected(db, errors.CheckViolation, insert_ss, se, 9, -5, "lb")
    rejected(db, errors.CheckViolation,
             "INSERT INTO session_sets (session_exercise_id, set_number, status, was_in_starting_plan, "
             "suggested_weight_snapshot) VALUES (%s,9,'pending',true,10)", se)  # snapshot weight without unit
    db.execute(insert_ts, (te, 9, 0, "kg"))  # zero is an explicit, valid weight
    db.execute(insert_ts, (te, 10, None, None))  # missing weight is valid for any category


# ---- completion timestamps -----------------------------------------------

def _set_in_finished_session(db):
    user = make_user(db)
    ex = make_provider_exercise(db, "Press")
    session = make_session(db, user, status="completed", finished=minutes(60))
    se = make_session_exercise(db, session, ex)
    return se, session


def test_completion_timestamp_rules(db):
    se, _ = _set_in_finished_session(db)
    base = ("INSERT INTO session_sets (session_exercise_id, set_number, status, was_in_starting_plan, actual_reps, "
            "completed_at, rest_started_at, rest_ended_at) VALUES (%s,%s,%s,false,%s,%s,%s,%s)")
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, None, None, None)                    # no completed_at
    rejected(db, errors.CheckViolation, base, se, 1, "pending", None, minutes(5), minutes(5), None)       # completed_at while pending
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, minutes(5), None, None)              # rest not started with completion
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, minutes(5), minutes(6), None)        # rest start != completion
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, minutes(5), minutes(5), minutes(4))  # rest ends before start
    rejected(db, errors.CheckViolation, base, se, 1, "completed", None, minutes(5), minutes(5), None)     # rep-based needs reps
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 0, minutes(5), minutes(5), None)        # reps must be positive
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, minutes(-5), minutes(-5), None)      # before session start
    rejected(db, errors.CheckViolation, base, se, 1, "completed", 8, minutes(90), minutes(90), None)      # after session finish
    db.execute(base, (se, 1, "completed", 8, minutes(5), minutes(5), minutes(7)))                         # valid


def test_session_finish_chronology(db):
    user = make_user(db)
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_sessions (user_id, name_snapshot, status, started_at, finished_at, template_update_status) "
             "VALUES (%s,'W','completed',%s,%s,'not_applicable')", user, minutes(10), minutes(5))
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_sessions (user_id, name_snapshot, status, started_at, finished_at, template_update_status) "
             "VALUES (%s,'W','in_progress',%s,%s,'not_applicable')", user, minutes(0), minutes(5))
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_sessions (user_id, name_snapshot, status, started_at, template_update_status) "
             "VALUES (%s,'W','completed',%s,'not_applicable')", user, minutes(0))


def test_shortening_a_session_cannot_orphan_completed_sets(db):
    se, session = _set_in_finished_session(db)
    db.execute("INSERT INTO session_sets (session_exercise_id, set_number, status, was_in_starting_plan, actual_reps, "
               "completed_at, rest_started_at) VALUES (%s,1,'completed',false,5,%s,%s)", (se, minutes(50), minutes(50)))
    rejected(db, errors.CheckViolation, "UPDATE workout_sessions SET finished_at=%s WHERE id=%s", minutes(20), session)


def test_logical_removal_rules(db):
    se, _ = _set_in_finished_session(db)
    ins = ("INSERT INTO session_sets (session_exercise_id, set_number, status, was_in_starting_plan, actual_reps, "
           "removed_at) VALUES (%s,%s,%s,false,%s,%s)")
    rejected(db, errors.CheckViolation, ins, se, 1, "pending", None, minutes(5))   # removal requires skipped
    rejected(db, errors.CheckViolation, ins, se, 1, "skipped", 5, minutes(5))      # cannot erase performance
    db.execute(ins, (se, 1, "skipped", None, minutes(5)))


def test_template_update_outcome_consistency(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    for sql in (
        "UPDATE workout_sessions SET template_update_status='declined' WHERE id=%s",                       # declined needs choice=false
        "UPDATE workout_sessions SET template_update_status='applied', template_update_requested=true WHERE id=%s",
        "UPDATE workout_sessions SET template_update_status='not_applicable' WHERE id=%s",                 # template-backed
        "UPDATE workout_sessions SET template_update_status='bogus' WHERE id=%s",
    ):
        rejected(db, errors.CheckViolation, sql, session)
    rejected(db, errors.CheckViolation,
             "INSERT INTO workout_sessions (user_id, source_template_id, name_snapshot, status, started_at, "
             "template_update_status) VALUES (%s,%s,'W','in_progress',%s,'pending')", user, plan, T0)  # id without version


# ---- deletion behaviour ----------------------------------------------------

def test_history_blocks_deleting_sources(db):
    user, ex, plan, te, ts, session = _templated_session(db)
    se = make_session_exercise(db, session, ex, te)
    make_session_set(db, se, 1, ts)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM workout_templates WHERE id=%s", plan)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM template_exercises WHERE id=%s", te)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM template_sets WHERE id=%s", ts)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM exercises WHERE id=%s", ex)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM users WHERE id=%s", user)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM workout_sessions WHERE id=%s", session)
    rejected(db, errors.ForeignKeyViolation, "DELETE FROM session_exercises WHERE id=%s", se)


def test_unreferenced_plan_deletes_cascade_and_copy_link_is_nulled(db):
    user = make_user(db)
    ex = make_provider_exercise(db, "Curl")
    sample = make_template(db, None, "S")
    copy = one(db, "INSERT INTO workout_templates (owner_user_id, template_type, name, copied_from_template_id) "
                   "VALUES (%s,'personal','C',%s) RETURNING id", user, sample)
    te = make_template_exercise(db, copy, ex)
    make_template_set(db, te)
    db.execute("DELETE FROM workout_templates WHERE id=%s", (sample,))
    assert one(db, "SELECT copied_from_template_id FROM workout_templates WHERE id=%s", copy) is None
    db.execute("DELETE FROM workout_templates WHERE id=%s", (copy,))
    assert one(db, "SELECT count(*) FROM template_sets WHERE template_exercise_id=%s", te) == 0
