-- 0001: the 13 approved application tables (docs/database/design.md).
-- Master records (exercise_categories, body_parts) are NOT inserted here;
-- that is a separate story. updated_at is kept current by a database trigger.
-- At most one in-progress workout per user is enforced by a partial unique index.

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(150) NOT NULL,
    contact_email VARCHAR(320),
    preferred_weight_unit VARCHAR(2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_display_name CHECK (display_name = btrim(display_name) AND display_name <> ''),
    CONSTRAINT ck_users_weight_unit CHECK (preferred_weight_unit IN ('kg', 'lb')),
    CONSTRAINT ck_users_status CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE user_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    provider VARCHAR(20) NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email_at_login VARCHAR(320),
    email_verified BOOLEAN,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_user_identities_provider CHECK (provider IN ('google', 'microsoft')),
    CONSTRAINT ck_user_identities_issuer CHECK (btrim(issuer) <> ''),
    CONSTRAINT ck_user_identities_subject CHECK (btrim(subject) <> ''),
    CONSTRAINT uq_user_identities_identity UNIQUE (provider, issuer, subject)
);
CREATE INDEX ix_user_identities_user_id ON user_identities (user_id);

CREATE TABLE exercise_categories (
    id SMALLINT PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    sort_order SMALLINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT ck_exercise_categories_name CHECK (btrim(name) <> ''),
    CONSTRAINT uq_exercise_categories_name UNIQUE (name),
    CONSTRAINT uq_exercise_categories_sort_order UNIQUE (sort_order)
);

CREATE TABLE body_parts (
    id SMALLINT PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    sort_order SMALLINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT ck_body_parts_name CHECK (btrim(name) <> ''),
    CONSTRAINT uq_body_parts_name UNIQUE (name),
    CONSTRAINT uq_body_parts_sort_order UNIQUE (sort_order)
);

CREATE TABLE exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    category_id SMALLINT NOT NULL REFERENCES exercise_categories (id) ON DELETE RESTRICT,
    body_part_id SMALLINT NOT NULL REFERENCES body_parts (id) ON DELETE RESTRICT,
    source_type VARCHAR(20) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_exercises_name CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT ck_exercises_source_type CHECK (source_type IN ('provider', 'custom'))
);
CREATE INDEX ix_exercises_category_id ON exercises (category_id);
CREATE INDEX ix_exercises_body_part_id ON exercises (body_part_id);
CREATE INDEX ix_exercises_lower_name_id ON exercises (lower(name), id);

CREATE TABLE provider_exercises (
    exercise_id UUID PRIMARY KEY REFERENCES exercises (id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL,
    provider_exercise_id TEXT NOT NULL,
    provider_body_part TEXT,
    provider_equipment TEXT,
    instructions JSONB,
    target_muscles JSONB,
    secondary_muscles JSONB,
    media_references JSONB,
    raw_payload JSONB,
    last_synced_at TIMESTAMPTZ NOT NULL,
    provider_updated_at TIMESTAMPTZ,
    CONSTRAINT ck_provider_exercises_provider_name CHECK (btrim(provider_name) <> ''),
    CONSTRAINT ck_provider_exercises_provider_exercise_id CHECK (btrim(provider_exercise_id) <> ''),
    CONSTRAINT ck_provider_exercises_instructions CHECK (jsonb_typeof(instructions) = 'array'),
    CONSTRAINT ck_provider_exercises_target_muscles CHECK (jsonb_typeof(target_muscles) = 'array'),
    CONSTRAINT ck_provider_exercises_secondary_muscles CHECK (jsonb_typeof(secondary_muscles) = 'array'),
    CONSTRAINT ck_provider_exercises_media_references CHECK (jsonb_typeof(media_references) = 'array'),
    CONSTRAINT ck_provider_exercises_raw_payload CHECK (jsonb_typeof(raw_payload) = 'object'),
    CONSTRAINT uq_provider_exercises_provider_key UNIQUE (provider_name, provider_exercise_id)
);

CREATE TABLE custom_exercises (
    exercise_id UUID PRIMARY KEY REFERENCES exercises (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT
);
CREATE INDEX ix_custom_exercises_created_by_user_id ON custom_exercises (created_by_user_id);

CREATE TABLE workout_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
    template_type VARCHAR(20) NOT NULL,
    name VARCHAR(150) NOT NULL,
    notes TEXT,
    copied_from_template_id UUID REFERENCES workout_templates (id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_workout_templates_type CHECK (template_type IN ('sample', 'personal')),
    CONSTRAINT ck_workout_templates_owner CHECK (
        (template_type = 'personal' AND owner_user_id IS NOT NULL)
        OR (template_type = 'sample' AND owner_user_id IS NULL)
    ),
    CONSTRAINT ck_workout_templates_name CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT ck_workout_templates_version CHECK (version > 0)
);
CREATE INDEX ix_workout_templates_owner_archived ON workout_templates (owner_user_id, archived_at);
CREATE INDEX ix_workout_templates_copied_from ON workout_templates (copied_from_template_id);

CREATE TABLE template_exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES workout_templates (id) ON DELETE CASCADE,
    exercise_id UUID NOT NULL REFERENCES exercises (id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    notes TEXT,
    CONSTRAINT ck_template_exercises_position CHECK (position > 0),
    CONSTRAINT uq_template_exercises_position UNIQUE (template_id, position) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX ix_template_exercises_exercise_id ON template_exercises (exercise_id);

CREATE TABLE template_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_exercise_id UUID NOT NULL REFERENCES template_exercises (id) ON DELETE CASCADE,
    set_number INTEGER NOT NULL,
    target_reps INTEGER,
    suggested_weight NUMERIC(10,3),
    weight_unit VARCHAR(2),
    rest_seconds INTEGER NOT NULL DEFAULT 120,
    CONSTRAINT ck_template_sets_set_number CHECK (set_number > 0),
    CONSTRAINT ck_template_sets_target_reps CHECK (target_reps IS NULL OR target_reps > 0),
    CONSTRAINT ck_template_sets_weight CHECK (suggested_weight IS NULL OR suggested_weight >= 0),
    CONSTRAINT ck_template_sets_weight_unit CHECK (
        (suggested_weight IS NULL AND weight_unit IS NULL)
        OR (suggested_weight IS NOT NULL AND weight_unit IS NOT NULL AND weight_unit IN ('kg', 'lb'))
    ),
    CONSTRAINT ck_template_sets_rest CHECK (rest_seconds >= 0),
    CONSTRAINT uq_template_sets_number UNIQUE (template_exercise_id, set_number)
);

CREATE TABLE workout_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    source_template_id UUID REFERENCES workout_templates (id) ON DELETE RESTRICT,
    source_template_version INTEGER,
    name_snapshot VARCHAR(150) NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    notes TEXT,
    template_updated_at TIMESTAMPTZ,
    template_update_requested BOOLEAN,
    template_update_status VARCHAR(20) NOT NULL,
    applied_template_id UUID REFERENCES workout_templates (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_workout_sessions_name CHECK (btrim(name_snapshot) <> ''),
    CONSTRAINT ck_workout_sessions_status CHECK (status IN ('in_progress', 'completed', 'cancelled')),
    CONSTRAINT ck_workout_sessions_finished CHECK (
        (status = 'in_progress' AND finished_at IS NULL)
        OR (status <> 'in_progress' AND finished_at IS NOT NULL AND finished_at >= started_at)
    ),
    CONSTRAINT ck_workout_sessions_source_pair CHECK (
        (source_template_id IS NULL AND source_template_version IS NULL)
        OR (source_template_id IS NOT NULL AND source_template_version IS NOT NULL AND source_template_version > 0)
    ),
    CONSTRAINT ck_workout_sessions_update_status CHECK (
        template_update_status IN ('not_applicable', 'pending', 'declined', 'applied', 'conflict')
    ),
    CONSTRAINT ck_workout_sessions_update_outcome CHECK (
        (template_update_status = 'not_applicable'
            AND source_template_id IS NULL AND template_update_requested IS NULL
            AND applied_template_id IS NULL AND template_updated_at IS NULL)
        OR (template_update_status = 'pending'
            AND source_template_id IS NOT NULL
            AND (template_update_requested IS NULL OR template_update_requested IS TRUE)
            AND applied_template_id IS NULL AND template_updated_at IS NULL)
        OR (template_update_status = 'declined'
            AND source_template_id IS NOT NULL AND template_update_requested IS FALSE
            AND applied_template_id IS NULL AND template_updated_at IS NULL)
        OR (template_update_status = 'applied'
            AND source_template_id IS NOT NULL AND template_update_requested IS TRUE
            AND status = 'completed'
            AND applied_template_id IS NOT NULL AND template_updated_at IS NOT NULL)
        OR (template_update_status = 'conflict'
            AND source_template_id IS NOT NULL AND template_update_requested IS TRUE
            AND applied_template_id IS NULL AND template_updated_at IS NULL)
    )
);
CREATE INDEX ix_workout_sessions_user_started ON workout_sessions (user_id, started_at DESC);
CREATE INDEX ix_workout_sessions_user_status ON workout_sessions (user_id, status);
CREATE UNIQUE INDEX ux_workout_sessions_one_in_progress_per_user
    ON workout_sessions (user_id) WHERE status = 'in_progress';
CREATE INDEX ix_workout_sessions_source_template ON workout_sessions (source_template_id);
CREATE INDEX ix_workout_sessions_applied_template ON workout_sessions (applied_template_id);

CREATE TABLE session_exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES workout_sessions (id) ON DELETE RESTRICT,
    exercise_id UUID NOT NULL REFERENCES exercises (id) ON DELETE RESTRICT,
    source_template_exercise_id UUID REFERENCES template_exercises (id) ON DELETE RESTRICT,
    name_snapshot VARCHAR(200) NOT NULL,
    category_snapshot VARCHAR(50) NOT NULL,
    body_part_snapshot VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL,
    notes TEXT,
    CONSTRAINT ck_session_exercises_name CHECK (btrim(name_snapshot) <> ''),
    CONSTRAINT ck_session_exercises_category CHECK (btrim(category_snapshot) <> ''),
    CONSTRAINT ck_session_exercises_body_part CHECK (btrim(body_part_snapshot) <> ''),
    CONSTRAINT ck_session_exercises_position CHECK (position > 0),
    CONSTRAINT uq_session_exercises_position UNIQUE (session_id, position) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX ix_session_exercises_exercise_id ON session_exercises (exercise_id);
CREATE INDEX ix_session_exercises_source_template_exercise ON session_exercises (source_template_exercise_id);

CREATE TABLE session_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_exercise_id UUID NOT NULL REFERENCES session_exercises (id) ON DELETE RESTRICT,
    source_template_set_id UUID REFERENCES template_sets (id) ON DELETE RESTRICT,
    set_number INTEGER NOT NULL,
    target_reps_snapshot INTEGER,
    suggested_weight_snapshot NUMERIC(10,3),
    suggested_weight_unit_snapshot VARCHAR(2),
    actual_reps INTEGER,
    actual_weight NUMERIC(10,3),
    weight_unit VARCHAR(2),
    status VARCHAR(20) NOT NULL,
    completed_at TIMESTAMPTZ,
    rest_seconds INTEGER NOT NULL DEFAULT 120,
    was_in_starting_plan BOOLEAN NOT NULL,
    removed_at TIMESTAMPTZ,
    rest_started_at TIMESTAMPTZ,
    rest_ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_session_sets_set_number CHECK (set_number > 0),
    CONSTRAINT ck_session_sets_target_reps CHECK (target_reps_snapshot IS NULL OR target_reps_snapshot > 0),
    CONSTRAINT ck_session_sets_suggested_weight CHECK (suggested_weight_snapshot IS NULL OR suggested_weight_snapshot >= 0),
    CONSTRAINT ck_session_sets_suggested_pair CHECK (
        (suggested_weight_snapshot IS NULL AND suggested_weight_unit_snapshot IS NULL)
        OR (suggested_weight_snapshot IS NOT NULL AND suggested_weight_unit_snapshot IS NOT NULL
            AND suggested_weight_unit_snapshot IN ('kg', 'lb'))
    ),
    CONSTRAINT ck_session_sets_actual_reps CHECK (actual_reps IS NULL OR actual_reps > 0),
    CONSTRAINT ck_session_sets_actual_weight CHECK (actual_weight IS NULL OR actual_weight >= 0),
    CONSTRAINT ck_session_sets_actual_pair CHECK (
        (actual_weight IS NULL AND weight_unit IS NULL)
        OR (actual_weight IS NOT NULL AND weight_unit IS NOT NULL AND weight_unit IN ('kg', 'lb'))
    ),
    CONSTRAINT ck_session_sets_status CHECK (status IN ('pending', 'completed', 'skipped')),
    CONSTRAINT ck_session_sets_completed_at CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
    CONSTRAINT ck_session_sets_rest CHECK (rest_seconds >= 0),
    CONSTRAINT ck_session_sets_rest_started CHECK (
        (status = 'completed' AND rest_started_at IS NOT NULL AND rest_started_at = completed_at)
        OR (status <> 'completed' AND rest_started_at IS NULL)
    ),
    CONSTRAINT ck_session_sets_rest_ended CHECK (
        rest_ended_at IS NULL OR (rest_started_at IS NOT NULL AND rest_ended_at >= rest_started_at)
    ),
    CONSTRAINT ck_session_sets_removed CHECK (
        removed_at IS NULL
        OR (status = 'skipped' AND actual_reps IS NULL AND actual_weight IS NULL
            AND weight_unit IS NULL AND completed_at IS NULL)
    ),
    CONSTRAINT ck_session_sets_added_rows CHECK (
        was_in_starting_plan
        OR (source_template_set_id IS NULL AND target_reps_snapshot IS NULL
            AND suggested_weight_snapshot IS NULL)
    ),
    CONSTRAINT uq_session_sets_number UNIQUE (session_exercise_id, set_number)
);
CREATE INDEX ix_session_sets_source_template_set ON session_sets (source_template_set_id);

-- ---------------------------------------------------------------------
-- Cross-table rules (a plain CHECK cannot see other tables).
-- ---------------------------------------------------------------------

CREATE FUNCTION fn_reject(p_message text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '%', p_message USING ERRCODE = '23514';
END $$;

-- Exactly one detail row, matching exercises.source_type.
CREATE FUNCTION fn_check_exercise_source(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_type text;
    v_provider boolean;
    v_custom boolean;
BEGIN
    SELECT source_type INTO v_type FROM exercises WHERE id = p_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_provider := EXISTS (SELECT 1 FROM provider_exercises WHERE exercise_id = p_id);
    v_custom := EXISTS (SELECT 1 FROM custom_exercises WHERE exercise_id = p_id);
    IF (v_type = 'provider' AND v_provider AND NOT v_custom)
       OR (v_type = 'custom' AND v_custom AND NOT v_provider) THEN
        RETURN;
    END IF;
    PERFORM fn_reject(format('exercise %s must have exactly one %s detail row', p_id, v_type));
END $$;

-- A custom exercise may be used only by a personal template of its creator.
CREATE FUNCTION fn_check_template_exercise(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    r record;
BEGIN
    SELECT t.template_type, t.owner_user_id, e.source_type, ce.created_by_user_id AS creator
      INTO r
      FROM template_exercises te
      JOIN workout_templates t ON t.id = te.template_id
      JOIN exercises e ON e.id = te.exercise_id
      LEFT JOIN custom_exercises ce ON ce.exercise_id = e.id
     WHERE te.id = p_id;
    IF NOT FOUND OR r.source_type <> 'custom' THEN
        RETURN;
    END IF;
    IF r.template_type <> 'personal' OR r.creator IS DISTINCT FROM r.owner_user_id THEN
        PERFORM fn_reject('template exercise may not use another user''s private custom exercise, and shared samples may not use custom exercises');
    END IF;
END $$;

-- Session exercise: private-exercise ownership and template lineage.
CREATE FUNCTION fn_check_session_exercise(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    r record;
BEGIN
    SELECT s.user_id, s.source_template_id, se.exercise_id, se.source_template_exercise_id,
           e.source_type, ce.created_by_user_id AS creator,
           te.template_id AS src_template_id, te.exercise_id AS src_exercise_id
      INTO r
      FROM session_exercises se
      JOIN workout_sessions s ON s.id = se.session_id
      JOIN exercises e ON e.id = se.exercise_id
      LEFT JOIN custom_exercises ce ON ce.exercise_id = e.id
      LEFT JOIN template_exercises te ON te.id = se.source_template_exercise_id
     WHERE se.id = p_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF r.source_type = 'custom' AND r.creator IS DISTINCT FROM r.user_id THEN
        PERFORM fn_reject('session exercise may not use another user''s private custom exercise');
    END IF;
    IF r.source_template_exercise_id IS NOT NULL
       AND (r.source_template_id IS NULL
            OR r.src_template_id <> r.source_template_id
            OR r.src_exercise_id <> r.exercise_id) THEN
        PERFORM fn_reject('session exercise source link must belong to the session''s source template and use the same exercise');
    END IF;
END $$;

-- Session set: source-set lineage, completion rules and chronology.
CREATE FUNCTION fn_check_session_set(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    r record;
BEGIN
    SELECT ss.*, se.source_template_exercise_id AS se_source, se.category_snapshot,
           ts.template_exercise_id AS ts_exercise, s.started_at AS s_started, s.finished_at AS s_finished
      INTO r
      FROM session_sets ss
      JOIN session_exercises se ON se.id = ss.session_exercise_id
      JOIN workout_sessions s ON s.id = se.session_id
      LEFT JOIN template_sets ts ON ts.id = ss.source_template_set_id
     WHERE ss.id = p_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF r.source_template_set_id IS NOT NULL
       AND (r.se_source IS NULL OR r.ts_exercise <> r.se_source) THEN
        PERFORM fn_reject('session set source link must belong to the session exercise''s source template exercise');
    END IF;
    -- Cardio/Duration time tracking is an open design decision, so they are exempt.
    IF r.status = 'completed' AND r.actual_reps IS NULL
       AND r.category_snapshot NOT IN ('Cardio', 'Duration') THEN
        PERFORM fn_reject('a completed rep-based set requires actual_reps');
    END IF;
    IF (r.completed_at IS NOT NULL AND (r.completed_at < r.s_started
            OR (r.s_finished IS NOT NULL AND r.completed_at > r.s_finished)))
       OR (r.removed_at IS NOT NULL AND (r.removed_at < r.s_started
            OR (r.s_finished IS NOT NULL AND r.removed_at > r.s_finished))) THEN
        PERFORM fn_reject('set timestamps must fall within the session start and finish times');
    END IF;
END $$;

-- Session level: applied template target, plus its exercises and sets.
CREATE FUNCTION fn_check_session(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    r record;
    x record;
BEGIN
    SELECT s.user_id, s.source_template_id, s.applied_template_id,
           src.template_type AS src_type,
           a.template_type AS a_type, a.owner_user_id AS a_owner, a.copied_from_template_id AS a_copied
      INTO r
      FROM workout_sessions s
      LEFT JOIN workout_templates src ON src.id = s.source_template_id
      LEFT JOIN workout_templates a ON a.id = s.applied_template_id
     WHERE s.id = p_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF r.applied_template_id IS NOT NULL THEN
        IF r.a_type <> 'personal' OR r.a_owner IS DISTINCT FROM r.user_id
           OR NOT COALESCE((r.src_type = 'personal' AND r.applied_template_id = r.source_template_id)
                           OR (r.src_type = 'sample' AND r.a_copied = r.source_template_id), false) THEN
            PERFORM fn_reject('applied template must be a personal template owned by the session user that is the source or a copy of the sample source');
        END IF;
    END IF;
    FOR x IN SELECT id FROM session_exercises WHERE session_id = p_id LOOP
        PERFORM fn_check_session_exercise(x.id);
    END LOOP;
    FOR x IN SELECT ss.id FROM session_sets ss
               JOIN session_exercises se ON se.id = ss.session_exercise_id
              WHERE se.session_id = p_id LOOP
        PERFORM fn_check_session_set(x.id);
    END LOOP;
END $$;

CREATE FUNCTION fn_check_exercise_references(p_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    x record;
BEGIN
    FOR x IN SELECT id FROM template_exercises WHERE exercise_id = p_id LOOP
        PERFORM fn_check_template_exercise(x.id);
    END LOOP;
    FOR x IN SELECT id FROM session_exercises WHERE exercise_id = p_id LOOP
        PERFORM fn_check_session_exercise(x.id);
    END LOOP;
END $$;

-- Trigger wrappers.
CREATE FUNCTION trg_exercises() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM fn_check_exercise_source(NEW.id);
    PERFORM fn_check_exercise_references(NEW.id);
    RETURN NULL;
END $$;

CREATE FUNCTION trg_exercise_details() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM fn_check_exercise_source(OLD.exercise_id);
        IF TG_TABLE_NAME = 'custom_exercises' THEN
            PERFORM fn_check_exercise_references(OLD.exercise_id);
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM fn_check_exercise_source(NEW.exercise_id);
        IF TG_TABLE_NAME = 'custom_exercises' THEN
            PERFORM fn_check_exercise_references(NEW.exercise_id);
        END IF;
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION trg_template_exercises() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    x record;
BEGIN
    PERFORM fn_check_template_exercise(NEW.id);
    FOR x IN SELECT id FROM session_exercises WHERE source_template_exercise_id = NEW.id LOOP
        PERFORM fn_check_session_exercise(x.id);
    END LOOP;
    RETURN NULL;
END $$;

CREATE FUNCTION trg_template_sets() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    x record;
BEGIN
    FOR x IN SELECT id FROM session_sets WHERE source_template_set_id = NEW.id LOOP
        PERFORM fn_check_session_set(x.id);
    END LOOP;
    RETURN NULL;
END $$;

CREATE FUNCTION trg_workout_templates() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    x record;
BEGIN
    FOR x IN SELECT id FROM template_exercises WHERE template_id = NEW.id LOOP
        PERFORM fn_check_template_exercise(x.id);
    END LOOP;
    FOR x IN SELECT id FROM workout_sessions
              WHERE applied_template_id = NEW.id OR source_template_id = NEW.id LOOP
        PERFORM fn_check_session(x.id);
    END LOOP;
    RETURN NULL;
END $$;

CREATE FUNCTION trg_workout_sessions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM fn_check_session(NEW.id);
    RETURN NULL;
END $$;

CREATE FUNCTION trg_session_exercises() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    x record;
BEGIN
    PERFORM fn_check_session_exercise(NEW.id);
    FOR x IN SELECT id FROM session_sets WHERE session_exercise_id = NEW.id LOOP
        PERFORM fn_check_session_set(x.id);
    END LOOP;
    RETURN NULL;
END $$;

CREATE FUNCTION trg_session_sets() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM fn_check_session_set(NEW.id);
    RETURN NULL;
END $$;

-- History immutability: starting-plan snapshots never change after capture.
CREATE FUNCTION trg_freeze_session() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_template_id IS DISTINCT FROM OLD.source_template_id
       OR NEW.source_template_version IS DISTINCT FROM OLD.source_template_version
       OR NEW.name_snapshot IS DISTINCT FROM OLD.name_snapshot THEN
        PERFORM fn_reject('workout session source and name snapshots are immutable');
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION trg_freeze_session_exercise() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.name_snapshot IS DISTINCT FROM OLD.name_snapshot
       OR NEW.category_snapshot IS DISTINCT FROM OLD.category_snapshot
       OR NEW.body_part_snapshot IS DISTINCT FROM OLD.body_part_snapshot THEN
        PERFORM fn_reject('session exercise snapshots are immutable');
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION trg_freeze_session_set() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.target_reps_snapshot IS DISTINCT FROM OLD.target_reps_snapshot
       OR NEW.suggested_weight_snapshot IS DISTINCT FROM OLD.suggested_weight_snapshot
       OR NEW.suggested_weight_unit_snapshot IS DISTINCT FROM OLD.suggested_weight_unit_snapshot
       OR NEW.was_in_starting_plan IS DISTINCT FROM OLD.was_in_starting_plan THEN
        PERFORM fn_reject('session set starting-plan snapshots are immutable');
    END IF;
    RETURN NEW;
END $$;

-- Deferred constraint triggers: validated at commit, so a service may insert
-- parent and child rows in any order within one transaction.
CREATE CONSTRAINT TRIGGER ct_exercises AFTER INSERT OR UPDATE ON exercises
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_exercises();
CREATE CONSTRAINT TRIGGER ct_provider_exercises AFTER INSERT OR UPDATE OR DELETE ON provider_exercises
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_exercise_details();
CREATE CONSTRAINT TRIGGER ct_custom_exercises AFTER INSERT OR UPDATE OR DELETE ON custom_exercises
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_exercise_details();
CREATE CONSTRAINT TRIGGER ct_template_exercises AFTER INSERT OR UPDATE ON template_exercises
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_template_exercises();
CREATE CONSTRAINT TRIGGER ct_template_sets AFTER UPDATE OF template_exercise_id ON template_sets
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_template_sets();
CREATE CONSTRAINT TRIGGER ct_workout_templates
    AFTER UPDATE OF owner_user_id, template_type, copied_from_template_id ON workout_templates
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_workout_templates();
CREATE CONSTRAINT TRIGGER ct_workout_sessions AFTER INSERT OR UPDATE ON workout_sessions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_workout_sessions();
CREATE CONSTRAINT TRIGGER ct_session_exercises AFTER INSERT OR UPDATE ON session_exercises
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_session_exercises();
CREATE CONSTRAINT TRIGGER ct_session_sets AFTER INSERT OR UPDATE ON session_sets
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_session_sets();

CREATE TRIGGER tr_freeze_session BEFORE UPDATE ON workout_sessions
    FOR EACH ROW EXECUTE FUNCTION trg_freeze_session();
CREATE TRIGGER tr_freeze_session_exercise BEFORE UPDATE ON session_exercises
    FOR EACH ROW EXECUTE FUNCTION trg_freeze_session_exercise();
CREATE TRIGGER tr_freeze_session_set BEFORE UPDATE ON session_sets
    FOR EACH ROW EXECUTE FUNCTION trg_freeze_session_set();

-- updated_at maintenance (design decision 10): set on every UPDATE.
CREATE FUNCTION trg_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER tr_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER tr_exercises_updated_at BEFORE UPDATE ON exercises
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER tr_workout_templates_updated_at BEFORE UPDATE ON workout_templates
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER tr_workout_sessions_updated_at BEFORE UPDATE ON workout_sessions
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE TRIGGER tr_session_sets_updated_at BEFORE UPDATE ON session_sets
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
