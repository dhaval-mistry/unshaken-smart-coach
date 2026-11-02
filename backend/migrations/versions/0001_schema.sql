CREATE TABLE body_parts (
	id SMALLINT NOT NULL,
	name VARCHAR(50) NOT NULL,
	sort_order SMALLINT NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	CONSTRAINT pk_body_parts PRIMARY KEY (id),
	CONSTRAINT ck_body_parts_1 CHECK (name = btrim(name) AND name <> ''),
	CONSTRAINT uq_body_parts_name UNIQUE (name),
	CONSTRAINT uq_body_parts_sort_order UNIQUE (sort_order)
)

;


CREATE TABLE exercise_categories (
	id SMALLINT NOT NULL,
	name VARCHAR(50) NOT NULL,
	sort_order SMALLINT NOT NULL,
	measurement_kind VARCHAR(20) NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	CONSTRAINT pk_exercise_categories PRIMARY KEY (id),
	CONSTRAINT ck_exercise_categories_1 CHECK (measurement_kind IN ('reps', 'duration', 'duration_distance')),
	CONSTRAINT ck_exercise_categories_2 CHECK (name = btrim(name) AND name <> ''),
	CONSTRAINT uq_exercise_categories_name UNIQUE (name),
	CONSTRAINT uq_exercise_categories_sort_order UNIQUE (sort_order)
)

;


CREATE TABLE users (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	display_name VARCHAR(150) NOT NULL,
	contact_email VARCHAR(320),
	preferred_weight_unit VARCHAR(2) NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT ck_users_1 CHECK (preferred_weight_unit IN ('kg', 'lb')),
	CONSTRAINT ck_users_2 CHECK (status IN ('active', 'disabled')),
	CONSTRAINT ck_users_3 CHECK (display_name = btrim(display_name) AND display_name <> '')
)

;


CREATE TABLE exercises (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	name VARCHAR(200) NOT NULL,
	category_id SMALLINT NOT NULL,
	body_part_id SMALLINT NOT NULL,
	source_type VARCHAR(20) NOT NULL,
	description TEXT,
	is_active BOOLEAN DEFAULT true NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_exercises PRIMARY KEY (id),
	CONSTRAINT ck_exercises_1 CHECK (source_type IN ('provider', 'custom')),
	CONSTRAINT ck_exercises_2 CHECK (name = btrim(name) AND name <> ''),
	CONSTRAINT fk_exercises_category_id FOREIGN KEY(category_id) REFERENCES exercise_categories (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
	CONSTRAINT fk_exercises_body_part_id FOREIGN KEY(body_part_id) REFERENCES body_parts (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)

;


CREATE TABLE user_identities (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	provider VARCHAR(20) NOT NULL,
	issuer TEXT NOT NULL,
	subject TEXT NOT NULL,
	email_at_login VARCHAR(320),
	email_verified BOOLEAN,
	last_login_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_user_identities PRIMARY KEY (id),
	CONSTRAINT ck_user_identities_1 CHECK (provider IN ('google', 'microsoft')),
	CONSTRAINT ck_user_identities_2 CHECK (issuer = btrim(issuer) AND issuer <> ''),
	CONSTRAINT ck_user_identities_3 CHECK (subject = btrim(subject) AND subject <> ''),
	CONSTRAINT uq_user_identities_provider_issuer_subject UNIQUE (provider, issuer, subject),
	CONSTRAINT fk_user_identities_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)

;


CREATE TABLE workout_templates (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	owner_user_id UUID,
	template_type VARCHAR(20) NOT NULL,
	name VARCHAR(150) NOT NULL,
	notes TEXT,
	copied_from_template_id UUID,
	copied_from_template_id_snapshot UUID,
	version INTEGER DEFAULT 1 NOT NULL,
	archived_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_workout_templates PRIMARY KEY (id),
	CONSTRAINT ck_workout_templates_1 CHECK (template_type IN ('sample', 'personal')),
	CONSTRAINT ck_workout_templates_2 CHECK (name = btrim(name) AND name <> ''),
	CONSTRAINT ck_workout_templates_3 CHECK (version > 0),
	CONSTRAINT ck_workout_templates_4 CHECK ((template_type = 'personal' AND owner_user_id IS NOT NULL) OR (template_type = 'sample' AND owner_user_id IS NULL)),
	CONSTRAINT ck_workout_templates_5 CHECK (copied_from_template_id IS NULL OR copied_from_template_id = copied_from_template_id_snapshot),
	CONSTRAINT fk_workout_templates_owner_user_id FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
	CONSTRAINT fk_workout_templates_copied_from_template_id FOREIGN KEY(copied_from_template_id) REFERENCES workout_templates (id) ON DELETE SET NULL ON UPDATE RESTRICT
)

;


CREATE TABLE custom_exercises (
	exercise_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	CONSTRAINT pk_custom_exercises PRIMARY KEY (exercise_id),
	CONSTRAINT fk_custom_exercises_exercise_id FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE ON UPDATE RESTRICT,
	CONSTRAINT fk_custom_exercises_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)

;


CREATE TABLE provider_exercises (
	exercise_id UUID NOT NULL,
	provider_name VARCHAR(50) NOT NULL,
	provider_exercise_id TEXT NOT NULL,
	provider_body_part TEXT,
	provider_equipment TEXT,
	instructions JSONB,
	target_muscles JSONB,
	secondary_muscles JSONB,
	media_references JSONB,
	raw_payload JSONB,
	last_synced_at TIMESTAMP WITH TIME ZONE NOT NULL,
	provider_updated_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_provider_exercises PRIMARY KEY (exercise_id),
	CONSTRAINT ck_provider_exercises_1 CHECK (provider_name = btrim(provider_name) AND provider_name <> ''),
	CONSTRAINT ck_provider_exercises_2 CHECK (provider_exercise_id = btrim(provider_exercise_id) AND provider_exercise_id <> ''),
	CONSTRAINT ck_provider_exercises_3 CHECK (instructions IS NULL OR jsonb_typeof(instructions) = 'array'),
	CONSTRAINT ck_provider_exercises_4 CHECK (target_muscles IS NULL OR jsonb_typeof(target_muscles) = 'array'),
	CONSTRAINT ck_provider_exercises_5 CHECK (secondary_muscles IS NULL OR jsonb_typeof(secondary_muscles) = 'array'),
	CONSTRAINT ck_provider_exercises_6 CHECK (media_references IS NULL OR jsonb_typeof(media_references) = 'array'),
	CONSTRAINT ck_provider_exercises_7 CHECK (raw_payload IS NULL OR jsonb_typeof(raw_payload) = 'object'),
	CONSTRAINT uq_provider_exercises_provider_name_provider_exercise_id UNIQUE (provider_name, provider_exercise_id),
	CONSTRAINT fk_provider_exercises_exercise_id FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE ON UPDATE RESTRICT
)

;


CREATE TABLE template_exercises (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	template_id UUID NOT NULL,
	exercise_id UUID NOT NULL,
	position INTEGER NOT NULL,
	notes TEXT,
	CONSTRAINT pk_template_exercises PRIMARY KEY (id),
	CONSTRAINT ck_template_exercises_1 CHECK (position > 0),
	CONSTRAINT uq_template_exercises_template_id_position UNIQUE (template_id, position) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT fk_template_exercises_template_id FOREIGN KEY(template_id) REFERENCES workout_templates (id) ON DELETE CASCADE ON UPDATE RESTRICT,
	CONSTRAINT fk_template_exercises_exercise_id FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)

;


CREATE TABLE workout_sessions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	source_template_id UUID,
	source_template_id_snapshot UUID,
	source_template_type_snapshot VARCHAR(20),
	source_template_version INTEGER,
	name_snapshot VARCHAR(150) NOT NULL,
	starting_plan_snapshot JSONB,
	status VARCHAR(20) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	notes TEXT,
	template_updated_at TIMESTAMP WITH TIME ZONE,
	template_update_requested BOOLEAN,
	template_update_status VARCHAR(20) NOT NULL,
	applied_template_id UUID,
	applied_template_id_snapshot UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_workout_sessions PRIMARY KEY (id),
	CONSTRAINT ck_workout_sessions_1 CHECK (source_template_type_snapshot IN ('sample', 'personal')),
	CONSTRAINT ck_workout_sessions_2 CHECK (status IN ('in_progress', 'completed', 'cancelled')),
	CONSTRAINT ck_workout_sessions_3 CHECK (template_update_status IN ('not_applicable', 'pending', 'declined', 'applied', 'conflict')),
	CONSTRAINT ck_workout_sessions_4 CHECK (source_template_version > 0),
	CONSTRAINT ck_workout_sessions_5 CHECK (name_snapshot = btrim(name_snapshot) AND name_snapshot <> ''),
	CONSTRAINT ck_workout_sessions_6 CHECK ((status = 'in_progress' AND finished_at IS NULL) OR (status IN ('completed','cancelled') AND finished_at IS NOT NULL AND finished_at >= started_at)),
	CONSTRAINT ck_workout_sessions_7 CHECK ((source_template_id_snapshot IS NULL AND source_template_type_snapshot IS NULL AND source_template_version IS NULL) OR (source_template_id_snapshot IS NOT NULL AND source_template_type_snapshot IS NOT NULL AND source_template_version IS NOT NULL)),
	CONSTRAINT ck_workout_sessions_8 CHECK (source_template_id IS NULL OR (source_template_id_snapshot IS NOT NULL AND source_template_id = source_template_id_snapshot)),
	CONSTRAINT ck_workout_sessions_9 CHECK (applied_template_id IS NULL OR (applied_template_id_snapshot IS NOT NULL AND applied_template_id = applied_template_id_snapshot)),
	CONSTRAINT ck_workout_sessions_10 CHECK ((template_update_status = 'not_applicable' AND source_template_id_snapshot IS NULL AND template_update_requested IS NULL AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)
OR (source_template_id_snapshot IS NOT NULL AND (
(template_update_status = 'pending' AND (template_update_requested IS NULL OR template_update_requested IS TRUE) AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)
OR (template_update_status = 'declined' AND template_update_requested IS FALSE AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)
OR (template_update_status = 'conflict' AND template_update_requested IS TRUE AND applied_template_id IS NULL AND applied_template_id_snapshot IS NULL AND template_updated_at IS NULL)
OR (template_update_status = 'applied' AND template_update_requested IS TRUE AND status = 'completed' AND applied_template_id_snapshot IS NOT NULL AND template_updated_at IS NOT NULL)))),
	CONSTRAINT ck_workout_sessions_11 CHECK (template_updated_at IS NULL OR template_updated_at >= finished_at),
	CONSTRAINT ck_workout_sessions_choice_at_finish CHECK (template_update_requested IS NULL OR status = 'completed'),
	CONSTRAINT ck_workout_sessions_finish_choice CHECK (status <> 'completed' OR source_template_id_snapshot IS NULL OR template_update_requested IS NOT NULL),
	CONSTRAINT fk_workout_sessions_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
	CONSTRAINT fk_workout_sessions_source_template_id FOREIGN KEY(source_template_id) REFERENCES workout_templates (id) ON DELETE SET NULL ON UPDATE RESTRICT,
	CONSTRAINT fk_workout_sessions_applied_template_id FOREIGN KEY(applied_template_id) REFERENCES workout_templates (id) ON DELETE SET NULL ON UPDATE RESTRICT
)

;


CREATE TABLE session_exercises (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	session_id UUID NOT NULL,
	exercise_id UUID,
	exercise_id_snapshot UUID NOT NULL,
	exercise_source_type_snapshot VARCHAR(20) NOT NULL,
	source_template_exercise_id UUID,
	source_template_exercise_id_snapshot UUID,
	name_snapshot VARCHAR(200) NOT NULL,
	category_snapshot VARCHAR(50) NOT NULL,
	body_part_snapshot VARCHAR(50) NOT NULL,
	measurement_kind_snapshot VARCHAR(20) NOT NULL,
	position INTEGER NOT NULL,
	notes TEXT,
	CONSTRAINT pk_session_exercises PRIMARY KEY (id),
	CONSTRAINT ck_session_exercises_1 CHECK (exercise_source_type_snapshot IN ('provider', 'custom')),
	CONSTRAINT ck_session_exercises_2 CHECK (measurement_kind_snapshot IN ('reps', 'duration', 'duration_distance')),
	CONSTRAINT ck_session_exercises_3 CHECK (name_snapshot = btrim(name_snapshot) AND name_snapshot <> ''),
	CONSTRAINT ck_session_exercises_4 CHECK (category_snapshot = btrim(category_snapshot) AND category_snapshot <> ''),
	CONSTRAINT ck_session_exercises_5 CHECK (body_part_snapshot = btrim(body_part_snapshot) AND body_part_snapshot <> ''),
	CONSTRAINT ck_session_exercises_6 CHECK (position > 0),
	CONSTRAINT uq_session_exercises_session_id_position UNIQUE (session_id, position) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT fk_session_exercises_session_id FOREIGN KEY(session_id) REFERENCES workout_sessions (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
	CONSTRAINT fk_session_exercises_exercise_id FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE SET NULL ON UPDATE RESTRICT,
	CONSTRAINT fk_session_exercises_source_template_exercise_id FOREIGN KEY(source_template_exercise_id) REFERENCES template_exercises (id) ON DELETE SET NULL ON UPDATE RESTRICT
)

;


CREATE TABLE template_sets (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	template_exercise_id UUID NOT NULL,
	set_number INTEGER NOT NULL,
	target_reps INTEGER,
	target_duration_seconds INTEGER,
	target_distance_meters NUMERIC(12, 3),
	suggested_weight NUMERIC(10, 3),
	weight_unit VARCHAR(2),
	rest_seconds INTEGER DEFAULT 120 NOT NULL,
	CONSTRAINT pk_template_sets PRIMARY KEY (id),
	CONSTRAINT ck_template_sets_1 CHECK (set_number > 0),
	CONSTRAINT ck_template_sets_2 CHECK (target_reps > 0),
	CONSTRAINT ck_template_sets_3 CHECK (target_duration_seconds > 0),
	CONSTRAINT ck_template_sets_4 CHECK (target_distance_meters > 0),
	CONSTRAINT ck_template_sets_5 CHECK (suggested_weight >= 0),
	CONSTRAINT ck_template_sets_6 CHECK (rest_seconds >= 0),
	CONSTRAINT ck_template_sets_7 CHECK ((suggested_weight IS NULL AND weight_unit IS NULL) OR (suggested_weight IS NOT NULL AND weight_unit IN ('kg', 'lb') AND weight_unit IS NOT NULL)),
	CONSTRAINT uq_template_sets_template_exercise_id_set_number UNIQUE (template_exercise_id, set_number) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_template_sets_target_distance_meters_finite CHECK (target_distance_meters < 'Infinity'::numeric),
	CONSTRAINT ck_template_sets_suggested_weight_finite CHECK (suggested_weight < 'Infinity'::numeric),
	CONSTRAINT fk_template_sets_template_exercise_id FOREIGN KEY(template_exercise_id) REFERENCES template_exercises (id) ON DELETE CASCADE ON UPDATE RESTRICT
)

;


CREATE TABLE session_sets (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	session_exercise_id UUID NOT NULL,
	source_template_set_id UUID,
	source_template_set_id_snapshot UUID,
	set_number INTEGER NOT NULL,
	target_reps_snapshot INTEGER,
	target_duration_seconds_snapshot INTEGER,
	target_distance_meters_snapshot NUMERIC(12, 3),
	suggested_weight_snapshot NUMERIC(10, 3),
	suggested_weight_unit_snapshot VARCHAR(2),
	actual_reps INTEGER,
	actual_duration_seconds INTEGER,
	actual_distance_meters NUMERIC(12, 3),
	actual_weight NUMERIC(10, 3),
	weight_unit VARCHAR(2),
	status VARCHAR(20) NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	rest_seconds INTEGER DEFAULT 120 NOT NULL,
	was_in_starting_plan BOOLEAN NOT NULL,
	rest_started_at TIMESTAMP WITH TIME ZONE,
	rest_ended_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_session_sets PRIMARY KEY (id),
	CONSTRAINT ck_session_sets_1 CHECK (status IN ('pending', 'completed', 'skipped')),
	CONSTRAINT ck_session_sets_2 CHECK (set_number > 0),
	CONSTRAINT ck_session_sets_3 CHECK (target_reps_snapshot > 0),
	CONSTRAINT ck_session_sets_4 CHECK (target_duration_seconds_snapshot > 0),
	CONSTRAINT ck_session_sets_5 CHECK (target_distance_meters_snapshot > 0),
	CONSTRAINT ck_session_sets_6 CHECK (suggested_weight_snapshot >= 0),
	CONSTRAINT ck_session_sets_7 CHECK (actual_reps > 0),
	CONSTRAINT ck_session_sets_8 CHECK (actual_duration_seconds > 0),
	CONSTRAINT ck_session_sets_9 CHECK (actual_distance_meters > 0),
	CONSTRAINT ck_session_sets_10 CHECK (actual_weight >= 0),
	CONSTRAINT ck_session_sets_11 CHECK (rest_seconds >= 0),
	CONSTRAINT ck_session_sets_12 CHECK ((suggested_weight_snapshot IS NULL AND suggested_weight_unit_snapshot IS NULL) OR (suggested_weight_snapshot IS NOT NULL AND suggested_weight_unit_snapshot IN ('kg', 'lb') AND suggested_weight_unit_snapshot IS NOT NULL)),
	CONSTRAINT ck_session_sets_13 CHECK ((actual_weight IS NULL AND weight_unit IS NULL) OR (actual_weight IS NOT NULL AND weight_unit IN ('kg', 'lb') AND weight_unit IS NOT NULL)),
	CONSTRAINT ck_session_sets_14 CHECK ((status = 'completed' AND completed_at IS NOT NULL AND rest_started_at IS NOT NULL AND completed_at = rest_started_at) OR (status <> 'completed' AND completed_at IS NULL AND rest_started_at IS NULL AND rest_ended_at IS NULL)),
	CONSTRAINT ck_session_sets_15 CHECK (rest_ended_at IS NULL OR (rest_started_at IS NOT NULL AND rest_ended_at >= rest_started_at)),
	CONSTRAINT ck_session_sets_16 CHECK (was_in_starting_plan OR (source_template_set_id IS NULL AND source_template_set_id_snapshot IS NULL AND target_reps_snapshot IS NULL AND target_duration_seconds_snapshot IS NULL AND target_distance_meters_snapshot IS NULL AND suggested_weight_snapshot IS NULL AND suggested_weight_unit_snapshot IS NULL)),
	CONSTRAINT uq_session_sets_session_exercise_id_set_number UNIQUE (session_exercise_id, set_number) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_session_sets_target_distance_meters_snapshot_finite CHECK (target_distance_meters_snapshot < 'Infinity'::numeric),
	CONSTRAINT ck_session_sets_suggested_weight_snapshot_finite CHECK (suggested_weight_snapshot < 'Infinity'::numeric),
	CONSTRAINT ck_session_sets_actual_distance_meters_finite CHECK (actual_distance_meters < 'Infinity'::numeric),
	CONSTRAINT ck_session_sets_actual_weight_finite CHECK (actual_weight < 'Infinity'::numeric),
	CONSTRAINT fk_session_sets_session_exercise_id FOREIGN KEY(session_exercise_id) REFERENCES session_exercises (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
	CONSTRAINT fk_session_sets_source_template_set_id FOREIGN KEY(source_template_set_id) REFERENCES template_sets (id) ON DELETE SET NULL ON UPDATE RESTRICT
)

;

CREATE INDEX ix_exercises_body_part_id ON exercises (body_part_id);

CREATE INDEX ix_exercises_category_id ON exercises (category_id);

CREATE INDEX ix_exercises_name_id ON exercises (lower(name), id);

CREATE INDEX ix_user_identities_user_id ON user_identities (user_id);

CREATE INDEX ix_workout_templates_copied_from_template_id ON workout_templates (copied_from_template_id);

CREATE INDEX ix_workout_templates_copied_from_template_id_snapshot ON workout_templates (copied_from_template_id_snapshot);

CREATE INDEX ix_workout_templates_owner_archive ON workout_templates (owner_user_id, archived_at);

CREATE INDEX ix_workout_templates_owner_user_id ON workout_templates (owner_user_id);

CREATE INDEX ix_custom_exercises_created_by_user_id ON custom_exercises (created_by_user_id);

CREATE INDEX ix_template_exercises_exercise_id ON template_exercises (exercise_id);

CREATE INDEX ix_template_exercises_template_id ON template_exercises (template_id);

CREATE INDEX ix_workout_sessions_applied_template_id ON workout_sessions (applied_template_id);

CREATE INDEX ix_workout_sessions_applied_template_id_snapshot ON workout_sessions (applied_template_id_snapshot);

CREATE INDEX ix_workout_sessions_source_template_id ON workout_sessions (source_template_id);

CREATE INDEX ix_workout_sessions_source_template_id_snapshot ON workout_sessions (source_template_id_snapshot);

CREATE INDEX ix_workout_sessions_user_id ON workout_sessions (user_id);

CREATE INDEX ix_workout_sessions_user_started ON workout_sessions (user_id, started_at DESC);

CREATE INDEX ix_workout_sessions_user_status ON workout_sessions (user_id, status);

CREATE UNIQUE INDEX uq_workout_sessions_one_active ON workout_sessions (user_id) WHERE status = 'in_progress';

CREATE INDEX ix_session_exercises_exercise_id ON session_exercises (exercise_id);

CREATE INDEX ix_session_exercises_exercise_id_snapshot ON session_exercises (exercise_id_snapshot);

CREATE INDEX ix_session_exercises_session_id ON session_exercises (session_id);

CREATE INDEX ix_session_exercises_source_template_exercise_id ON session_exercises (source_template_exercise_id);

CREATE INDEX ix_session_exercises_source_template_exercise_id_snapshot ON session_exercises (source_template_exercise_id_snapshot);

CREATE INDEX ix_template_sets_template_exercise_id ON template_sets (template_exercise_id);

CREATE INDEX ix_session_sets_session_exercise_id ON session_sets (session_exercise_id);

CREATE INDEX ix_session_sets_source_template_set_id ON session_sets (source_template_set_id);

CREATE INDEX ix_session_sets_source_template_set_id_snapshot ON session_sets (source_template_set_id_snapshot);
