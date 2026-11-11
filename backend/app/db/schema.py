"""SQLAlchemy Core tables matching the reviewed 13-table database design.

Alembic revisions use frozen SQL, so later metadata edits cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(naming_convention={
    "pk": "pk_%(table_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s", "ix": "ix_%(table_name)s_%(column_0_name)s",
})

users = sa.Table(
    "users", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("display_name", sa.String(150), nullable=False),
    sa.Column("contact_email", sa.String(320), nullable=True),
    sa.Column("preferred_weight_unit", sa.String(2), nullable=False),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.CheckConstraint("preferred_weight_unit IN ('kg', 'lb')", name="ck_users_1"),
    sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_2"),
    sa.CheckConstraint("display_name = btrim(display_name) AND display_name <> ''", name="ck_users_3"),
)

user_identities = sa.Table(
    "user_identities", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("provider", sa.String(20), nullable=False),
    sa.Column("issuer", sa.Text, nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("email_at_login", sa.String(320), nullable=True),
    sa.Column("email_verified", sa.Boolean, nullable=True),
    sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.CheckConstraint("provider IN ('google', 'microsoft')", name="ck_user_identities_1"),
    sa.CheckConstraint("issuer = btrim(issuer) AND issuer <> ''", name="ck_user_identities_2"),
    sa.CheckConstraint("subject = btrim(subject) AND subject <> ''", name="ck_user_identities_3"),
    sa.UniqueConstraint("provider", "issuer", "subject", name="uq_user_identities_provider_issuer_subject"),
)

exercise_categories = sa.Table(
    "exercise_categories", metadata,
    sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
    sa.Column("name", sa.String(50), nullable=False),
    sa.Column("sort_order", sa.SmallInteger, nullable=False),
    sa.Column("measurement_kind", sa.String(20), nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.CheckConstraint("measurement_kind IN ('reps', 'duration', 'duration_distance')", name="ck_exercise_categories_1"),
    sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_exercise_categories_2"),
    sa.UniqueConstraint("name", name="uq_exercise_categories_name"),
    sa.UniqueConstraint("sort_order", name="uq_exercise_categories_sort_order"),
)

body_parts = sa.Table(
    "body_parts", metadata,
    sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
    sa.Column("name", sa.String(50), nullable=False),
    sa.Column("sort_order", sa.SmallInteger, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_body_parts_1"),
    sa.UniqueConstraint("name", name="uq_body_parts_name"),
    sa.UniqueConstraint("sort_order", name="uq_body_parts_sort_order"),
)

exercises = sa.Table(
    "exercises", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("category_id", sa.SmallInteger, sa.ForeignKey("exercise_categories.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("body_part_id", sa.SmallInteger, sa.ForeignKey("body_parts.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("source_type", sa.String(20), nullable=False),
    sa.Column("description", sa.Text, nullable=True),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    # Added by 0003; keeping it last preserves the frozen 0001 physical order.
    sa.Column("measurement_kind", sa.String(20), nullable=False),
    sa.CheckConstraint("measurement_kind IN ('reps','duration','duration_distance')", name="ck_exercises_measurement_kind"),
    sa.CheckConstraint("source_type IN ('provider', 'custom')", name="ck_exercises_1"),
    sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_exercises_2"),
)

provider_exercises = sa.Table(
    "provider_exercises", metadata,
    sa.Column("exercise_id", UUID(as_uuid=True), sa.ForeignKey("exercises.id", ondelete="CASCADE", onupdate="RESTRICT"), primary_key=True),
    sa.Column("provider_name", sa.String(50), nullable=False),
    sa.Column("provider_exercise_id", sa.Text, nullable=False),
    sa.Column("provider_body_part", sa.Text, nullable=True),
    sa.Column("provider_equipment", sa.Text, nullable=True),
    sa.Column("instructions", JSONB, nullable=True),
    sa.Column("target_muscles", JSONB, nullable=True),
    sa.Column("secondary_muscles", JSONB, nullable=True),
    sa.Column("media_references", JSONB, nullable=True),
    sa.Column("raw_payload", JSONB, nullable=True),
    sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("provider_name = btrim(provider_name) AND provider_name <> ''", name="ck_provider_exercises_1"),
    sa.CheckConstraint("provider_exercise_id = btrim(provider_exercise_id) AND provider_exercise_id <> ''", name="ck_provider_exercises_2"),
    sa.CheckConstraint("instructions IS NULL OR jsonb_typeof(instructions) = 'array'", name="ck_provider_exercises_3"),
    sa.CheckConstraint("target_muscles IS NULL OR jsonb_typeof(target_muscles) = 'array'", name="ck_provider_exercises_4"),
    sa.CheckConstraint("secondary_muscles IS NULL OR jsonb_typeof(secondary_muscles) = 'array'", name="ck_provider_exercises_5"),
    sa.CheckConstraint("media_references IS NULL OR jsonb_typeof(media_references) = 'array'", name="ck_provider_exercises_6"),
    sa.CheckConstraint("raw_payload IS NULL OR jsonb_typeof(raw_payload) = 'object'", name="ck_provider_exercises_7"),
    sa.UniqueConstraint("provider_name", "provider_exercise_id", name="uq_provider_exercises_provider_name_provider_exercise_id"),
)

custom_exercises = sa.Table(
    "custom_exercises", metadata,
    sa.Column("exercise_id", UUID(as_uuid=True), sa.ForeignKey("exercises.id", ondelete="CASCADE", onupdate="RESTRICT"), primary_key=True),
    sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
)

workout_templates = sa.Table(
    "workout_templates", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True),
    sa.Column("template_type", sa.String(20), nullable=False),
    sa.Column("name", sa.String(150), nullable=False),
    sa.Column("notes", sa.Text, nullable=True),
    sa.Column("copied_from_template_id", UUID(as_uuid=True), sa.ForeignKey("workout_templates.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("copied_from_template_id_snapshot", UUID(as_uuid=True), nullable=True),
    sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.CheckConstraint("template_type IN ('sample', 'personal')", name="ck_workout_templates_1"),
    sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_workout_templates_2"),
    sa.CheckConstraint("version > 0", name="ck_workout_templates_3"),
    sa.CheckConstraint("(template_type = 'personal' AND owner_user_id IS NOT NULL) OR (template_type = 'sample' AND owner_user_id IS NULL)", name="ck_workout_templates_4"),
    sa.CheckConstraint("copied_from_template_id IS NULL OR copied_from_template_id = copied_from_template_id_snapshot", name="ck_workout_templates_5"),
)

template_exercises = sa.Table(
    "template_exercises", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("workout_templates.id", ondelete="CASCADE", onupdate="RESTRICT"), nullable=False),
    sa.Column("exercise_id", UUID(as_uuid=True), sa.ForeignKey("exercises.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("notes", sa.Text, nullable=True),
    sa.CheckConstraint("position > 0", name="ck_template_exercises_1"),
    sa.UniqueConstraint("template_id", "position", name="uq_template_exercises_template_id_position", deferrable=True, initially="IMMEDIATE"),
)

template_sets = sa.Table(
    "template_sets", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("template_exercise_id", UUID(as_uuid=True), sa.ForeignKey("template_exercises.id", ondelete="CASCADE", onupdate="RESTRICT"), nullable=False),
    sa.Column("set_number", sa.Integer, nullable=False),
    sa.Column("target_reps", sa.Integer, nullable=True),
    sa.Column("target_duration_seconds", sa.Integer, nullable=True),
    sa.Column("target_distance_meters", sa.Numeric(12,3), nullable=True),
    sa.Column("suggested_weight", sa.Numeric(10,3), nullable=True),
    sa.Column("weight_unit", sa.String(2), nullable=True),
    sa.Column("rest_seconds", sa.Integer, nullable=False, server_default=sa.text("120")),
    sa.CheckConstraint("set_number > 0", name="ck_template_sets_1"),
    sa.CheckConstraint("target_reps > 0", name="ck_template_sets_2"),
    sa.CheckConstraint("target_duration_seconds > 0", name="ck_template_sets_3"),
    sa.CheckConstraint("target_distance_meters > 0", name="ck_template_sets_4"),
    sa.CheckConstraint("suggested_weight >= 0", name="ck_template_sets_5"),
    sa.CheckConstraint("rest_seconds >= 0", name="ck_template_sets_6"),
    sa.CheckConstraint("(suggested_weight IS NULL AND weight_unit IS NULL) OR (suggested_weight IS NOT NULL AND weight_unit IN ('kg', 'lb') AND weight_unit IS NOT NULL)", name="ck_template_sets_7"),
    sa.UniqueConstraint("template_exercise_id", "set_number", name="uq_template_sets_template_exercise_id_set_number", deferrable=True, initially="IMMEDIATE"),
    sa.CheckConstraint("target_distance_meters < 'Infinity'::numeric", name="ck_template_sets_target_distance_meters_finite"),
    sa.CheckConstraint("suggested_weight < 'Infinity'::numeric", name="ck_template_sets_suggested_weight_finite"),
)

workout_sessions = sa.Table(
    "workout_sessions", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("source_template_id", UUID(as_uuid=True), sa.ForeignKey("workout_templates.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("source_template_id_snapshot", UUID(as_uuid=True), nullable=True),
    sa.Column("source_template_type_snapshot", sa.String(20), nullable=True),
    sa.Column("source_template_version", sa.Integer, nullable=True),
    sa.Column("name_snapshot", sa.String(150), nullable=False),
    sa.Column("starting_plan_snapshot", JSONB, nullable=True),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("notes", sa.Text, nullable=True),
    sa.Column("template_updated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("template_update_requested", sa.Boolean, nullable=True),
    sa.Column("template_update_status", sa.String(20), nullable=False),
    sa.Column("applied_template_id", UUID(as_uuid=True), sa.ForeignKey("workout_templates.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("applied_template_id_snapshot", UUID(as_uuid=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.CheckConstraint("source_template_type_snapshot IN ('sample', 'personal')", name="ck_workout_sessions_1"),
    sa.CheckConstraint("status IN ('in_progress', 'completed', 'cancelled')", name="ck_workout_sessions_2"),
    sa.CheckConstraint("template_update_status IN ('not_applicable', 'pending', 'declined', 'applied', 'conflict')", name="ck_workout_sessions_3"),
    sa.CheckConstraint("source_template_version > 0", name="ck_workout_sessions_4"),
    sa.CheckConstraint("name_snapshot = btrim(name_snapshot) AND name_snapshot <> ''", name="ck_workout_sessions_5"),
    sa.CheckConstraint("(status = 'in_progress' AND finished_at IS NULL) OR (status IN ('completed','cancelled') AND finished_at IS NOT NULL AND finished_at >= started_at)", name="ck_workout_sessions_6"),
    sa.CheckConstraint("(source_template_id_snapshot IS NULL AND source_template_type_snapshot IS NULL AND source_template_version IS NULL) OR (source_template_id_snapshot IS NOT NULL AND source_template_type_snapshot IS NOT NULL AND source_template_version IS NOT NULL)", name="ck_workout_sessions_7"),
    sa.CheckConstraint("source_template_id IS NULL OR (source_template_id_snapshot IS NOT NULL AND source_template_id = source_template_id_snapshot)", name="ck_workout_sessions_8"),
    sa.CheckConstraint("applied_template_id IS NULL OR (applied_template_id_snapshot IS NOT NULL AND applied_template_id = applied_template_id_snapshot)", name="ck_workout_sessions_9"),
    sa.CheckConstraint("(template_update_status = 'not_applicable' AND source_template_id_snapshot IS NULL AND template_update_requested IS NULL AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)\nOR (source_template_id_snapshot IS NOT NULL AND (\n(template_update_status = 'pending' AND (template_update_requested IS NULL OR template_update_requested IS TRUE) AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)\nOR (template_update_status = 'declined' AND template_update_requested IS FALSE AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)\nOR (template_update_status = 'conflict' AND template_update_requested IS TRUE AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)\nOR (template_update_status = 'applied' AND template_update_requested IS TRUE AND status = 'completed' AND applied_template_id_snapshot IS NOT NULL AND template_updated_at IS NOT NULL)))", name="ck_workout_sessions_10"),
    sa.CheckConstraint("template_updated_at IS NULL OR template_updated_at >= finished_at", name="ck_workout_sessions_11"),
    sa.CheckConstraint("template_update_requested IS NULL OR status = 'completed'", name="ck_workout_sessions_choice_at_finish"),
    sa.CheckConstraint("status <> 'completed' OR source_template_id_snapshot IS NULL OR template_update_requested IS NOT NULL", name="ck_workout_sessions_finish_choice"),
)

session_exercises = sa.Table(
    "session_exercises", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("workout_sessions.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("exercise_id", UUID(as_uuid=True), sa.ForeignKey("exercises.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("exercise_id_snapshot", UUID(as_uuid=True), nullable=False),
    sa.Column("exercise_source_type_snapshot", sa.String(20), nullable=False),
    sa.Column("source_template_exercise_id", UUID(as_uuid=True), sa.ForeignKey("template_exercises.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("source_template_exercise_id_snapshot", UUID(as_uuid=True), nullable=True),
    sa.Column("name_snapshot", sa.String(200), nullable=False),
    sa.Column("category_snapshot", sa.String(50), nullable=False),
    sa.Column("body_part_snapshot", sa.String(50), nullable=False),
    sa.Column("measurement_kind_snapshot", sa.String(20), nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("notes", sa.Text, nullable=True),
    sa.CheckConstraint("exercise_source_type_snapshot IN ('provider', 'custom')", name="ck_session_exercises_1"),
    sa.CheckConstraint("measurement_kind_snapshot IN ('reps', 'duration', 'duration_distance')", name="ck_session_exercises_2"),
    sa.CheckConstraint("name_snapshot = btrim(name_snapshot) AND name_snapshot <> ''", name="ck_session_exercises_3"),
    sa.CheckConstraint("category_snapshot = btrim(category_snapshot) AND category_snapshot <> ''", name="ck_session_exercises_4"),
    sa.CheckConstraint("body_part_snapshot = btrim(body_part_snapshot) AND body_part_snapshot <> ''", name="ck_session_exercises_5"),
    sa.CheckConstraint("position > 0", name="ck_session_exercises_6"),
    sa.UniqueConstraint("session_id", "position", name="uq_session_exercises_session_id_position", deferrable=True, initially="IMMEDIATE"),
)

session_sets = sa.Table(
    "session_sets", metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("session_exercise_id", UUID(as_uuid=True), sa.ForeignKey("session_exercises.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
    sa.Column("source_template_set_id", UUID(as_uuid=True), sa.ForeignKey("template_sets.id", ondelete="SET NULL", onupdate="RESTRICT"), nullable=True),
    sa.Column("source_template_set_id_snapshot", UUID(as_uuid=True), nullable=True),
    sa.Column("set_number", sa.Integer, nullable=False),
    sa.Column("target_reps_snapshot", sa.Integer, nullable=True),
    sa.Column("target_duration_seconds_snapshot", sa.Integer, nullable=True),
    sa.Column("target_distance_meters_snapshot", sa.Numeric(12,3), nullable=True),
    sa.Column("suggested_weight_snapshot", sa.Numeric(10,3), nullable=True),
    sa.Column("suggested_weight_unit_snapshot", sa.String(2), nullable=True),
    sa.Column("actual_reps", sa.Integer, nullable=True),
    sa.Column("actual_duration_seconds", sa.Integer, nullable=True),
    sa.Column("actual_distance_meters", sa.Numeric(12,3), nullable=True),
    sa.Column("actual_weight", sa.Numeric(10,3), nullable=True),
    sa.Column("weight_unit", sa.String(2), nullable=True),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("rest_seconds", sa.Integer, nullable=False, server_default=sa.text("120")),
    sa.Column("was_in_starting_plan", sa.Boolean, nullable=False),
    sa.Column("rest_started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("rest_ended_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.CheckConstraint("status IN ('pending','completed','skipped','cancelled')", name="ck_session_sets_1"),
    sa.CheckConstraint("status <> 'cancelled' OR (actual_reps IS NULL AND actual_duration_seconds IS NULL AND actual_distance_meters IS NULL AND actual_weight IS NULL AND weight_unit IS NULL AND completed_at IS NULL AND rest_started_at IS NULL AND rest_ended_at IS NULL)", name="ck_session_sets_cancelled_empty"),
    sa.CheckConstraint("set_number > 0", name="ck_session_sets_2"),
    sa.CheckConstraint("target_reps_snapshot > 0", name="ck_session_sets_3"),
    sa.CheckConstraint("target_duration_seconds_snapshot > 0", name="ck_session_sets_4"),
    sa.CheckConstraint("target_distance_meters_snapshot > 0", name="ck_session_sets_5"),
    sa.CheckConstraint("suggested_weight_snapshot >= 0", name="ck_session_sets_6"),
    sa.CheckConstraint("actual_reps > 0", name="ck_session_sets_7"),
    sa.CheckConstraint("actual_duration_seconds > 0", name="ck_session_sets_8"),
    sa.CheckConstraint("actual_distance_meters > 0", name="ck_session_sets_9"),
    sa.CheckConstraint("actual_weight >= 0", name="ck_session_sets_10"),
    sa.CheckConstraint("rest_seconds >= 0", name="ck_session_sets_11"),
    sa.CheckConstraint("(suggested_weight_snapshot IS NULL AND suggested_weight_unit_snapshot IS NULL) OR (suggested_weight_snapshot IS NOT NULL AND suggested_weight_unit_snapshot IN ('kg', 'lb') AND suggested_weight_unit_snapshot IS NOT NULL)", name="ck_session_sets_12"),
    sa.CheckConstraint("(actual_weight IS NULL AND weight_unit IS NULL) OR (actual_weight IS NOT NULL AND weight_unit IN ('kg', 'lb') AND weight_unit IS NOT NULL)", name="ck_session_sets_13"),
    sa.CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL AND rest_started_at IS NOT NULL AND completed_at = rest_started_at) OR (status <> 'completed' AND completed_at IS NULL AND rest_started_at IS NULL AND rest_ended_at IS NULL)", name="ck_session_sets_14"),
    sa.CheckConstraint("rest_ended_at IS NULL OR (rest_started_at IS NOT NULL AND rest_ended_at >= rest_started_at)", name="ck_session_sets_15"),
    sa.CheckConstraint("was_in_starting_plan OR (source_template_set_id IS NULL AND source_template_set_id_snapshot IS NULL AND target_reps_snapshot IS NULL AND target_duration_seconds_snapshot IS NULL AND target_distance_meters_snapshot IS NULL AND suggested_weight_snapshot IS NULL AND suggested_weight_unit_snapshot IS NULL)", name="ck_session_sets_16"),
    sa.UniqueConstraint("session_exercise_id", "set_number", name="uq_session_sets_session_exercise_id_set_number", deferrable=True, initially="IMMEDIATE"),
    sa.CheckConstraint("target_distance_meters_snapshot < 'Infinity'::numeric", name="ck_session_sets_target_distance_meters_snapshot_finite"),
    sa.CheckConstraint("suggested_weight_snapshot < 'Infinity'::numeric", name="ck_session_sets_suggested_weight_snapshot_finite"),
    sa.CheckConstraint("actual_distance_meters < 'Infinity'::numeric", name="ck_session_sets_actual_distance_meters_finite"),
    sa.CheckConstraint("actual_weight < 'Infinity'::numeric", name="ck_session_sets_actual_weight_finite"),
)

# Every referencing FK has an index; shared subtype primary keys already do.
for table in metadata.tables.values():
    for column in table.columns:
        if column.foreign_keys and not column.primary_key:
            sa.Index(f"ix_{table.name}_{column.name}", column)
        if column.name.endswith("_id_snapshot"):
            sa.Index(f"ix_{table.name}_{column.name}", column)

sa.Index("ix_workout_templates_owner_archive", workout_templates.c.owner_user_id, workout_templates.c.archived_at)
sa.Index("ix_workout_sessions_user_started", workout_sessions.c.user_id, workout_sessions.c.started_at.desc())
sa.Index("ix_workout_sessions_user_status", workout_sessions.c.user_id, workout_sessions.c.status)
sa.Index("uq_workout_sessions_one_active", workout_sessions.c.user_id, unique=True,
         postgresql_where=workout_sessions.c.status == "in_progress")
sa.Index("ix_exercises_name_id", sa.func.lower(exercises.c.name), exercises.c.id)
