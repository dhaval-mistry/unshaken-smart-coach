-- Frozen version-one database guards. No application/provider network calls.
CREATE FUNCTION usc_fail(message text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = message; END $$;

CREATE FUNCTION usc_measurement(kind text, reps integer, duration integer, distance numeric, complete boolean)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
SELECT CASE kind
 WHEN 'reps' THEN duration IS NULL AND distance IS NULL AND (NOT complete OR reps IS NOT NULL)
 WHEN 'duration' THEN reps IS NULL AND distance IS NULL AND (NOT complete OR duration IS NOT NULL)
 WHEN 'duration_distance' THEN reps IS NULL AND (NOT complete OR (duration IS NOT NULL AND distance IS NOT NULL))
 ELSE false END
 AND (reps IS NULL OR reps > 0) AND (duration IS NULL OR duration > 0)
 AND (distance IS NULL OR (distance > 0 AND distance <> 'NaN'::numeric))
$$;

CREATE FUNCTION usc_snapshot(session_document jsonb) RETURNS jsonb LANGUAGE sql STABLE AS $$
SELECT jsonb_build_object(
 'schema_version', 1,
 'source', CASE WHEN session_document->>'source_template_id_snapshot' IS NULL THEN 'null'::jsonb
 ELSE jsonb_build_object('template_id', session_document->>'source_template_id_snapshot',
 'template_type', session_document->>'source_template_type_snapshot',
 'version', (session_document->>'source_template_version')::integer) END,
 'exercises', COALESCE((
 SELECT jsonb_agg(jsonb_build_object(
 'session_exercise_id', e.id::text, 'exercise_id', e.exercise_id_snapshot::text,
 'exercise_source_type', e.exercise_source_type_snapshot,
 'source_template_exercise_id', e.source_template_exercise_id_snapshot::text,
 'name', e.name_snapshot, 'category', e.category_snapshot, 'body_part', e.body_part_snapshot,
 'measurement_kind', e.measurement_kind_snapshot, 'position', e.position,
 'sets', COALESCE((SELECT jsonb_agg(jsonb_build_object(
 'session_set_id', s.id::text, 'source_template_set_id', s.source_template_set_id_snapshot::text,
 'set_number', s.set_number, 'target_reps', s.target_reps_snapshot,
 'target_duration_seconds', s.target_duration_seconds_snapshot,
 'target_distance_meters', s.target_distance_meters_snapshot::text,
 'suggested_weight', s.suggested_weight_snapshot::text,
 'suggested_weight_unit', s.suggested_weight_unit_snapshot, 'rest_seconds', s.rest_seconds
 ) ORDER BY s.set_number) FROM session_sets s WHERE s.session_exercise_id=e.id), '[]'::jsonb)
 ) ORDER BY e.position) FROM session_exercises e WHERE e.session_id=(session_document->>'id')::uuid
 ), '[]'::jsonb))
$$;

CREATE FUNCTION usc_normalize_snapshot(document jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE ex jsonb; item jsonb; field text; result jsonb; normalized_ex jsonb;
 normalized_sets jsonb; exercises_result jsonb := '[]'; value text;
BEGIN
 IF jsonb_typeof(document) <> 'object' OR
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document) k)
      IS DISTINCT FROM ARRAY['exercises','schema_version','source']::text[] OR
    document->'schema_version' <> '1'::jsonb OR jsonb_typeof(document->'exercises') <> 'array'
 THEN PERFORM usc_fail('Invalid initial snapshot root'); END IF;
 IF document->'source' <> 'null'::jsonb THEN
   IF jsonb_typeof(document->'source') <> 'object' OR
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document->'source') k)
      IS DISTINCT FROM ARRAY['template_id','template_type','version']::text[] OR
    jsonb_typeof(document->'source'->'template_id') <> 'string' OR
    jsonb_typeof(document->'source'->'template_type') <> 'string' OR
    jsonb_typeof(document->'source'->'version') <> 'number' OR
    (document->'source'->>'version') !~ '^[1-9][0-9]*$'
   THEN PERFORM usc_fail('Invalid snapshot source'); END IF;
 END IF;
 FOR ex IN SELECT * FROM jsonb_array_elements(document->'exercises') LOOP
   IF jsonb_typeof(ex) <> 'object' OR
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(ex) k)
      IS DISTINCT FROM ARRAY['body_part','category','exercise_id','exercise_source_type','measurement_kind',
         'name','position','session_exercise_id','sets','source_template_exercise_id']::text[]
    OR jsonb_typeof(ex->'sets') <> 'array' OR jsonb_typeof(ex->'position') <> 'number'
    OR (ex->>'position') !~ '^[1-9][0-9]*$'
   THEN PERFORM usc_fail('Invalid snapshot exercise'); END IF;
   FOREACH field IN ARRAY ARRAY['body_part','category','exercise_id','exercise_source_type','measurement_kind','name','session_exercise_id'] LOOP
     IF jsonb_typeof(ex->field) <> 'string' THEN PERFORM usc_fail('Invalid snapshot exercise field type'); END IF;
   END LOOP;
   IF jsonb_typeof(ex->'source_template_exercise_id') NOT IN ('string','null')
   THEN PERFORM usc_fail('Invalid snapshot source entry type'); END IF;
   normalized_sets := '[]';
   FOR item IN SELECT * FROM jsonb_array_elements(ex->'sets') LOOP
     IF jsonb_typeof(item) <> 'object' OR
      (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(item) k)
       IS DISTINCT FROM ARRAY['rest_seconds','session_set_id','set_number','source_template_set_id',
        'suggested_weight','suggested_weight_unit','target_distance_meters','target_duration_seconds','target_reps']::text[]
      OR jsonb_typeof(item->'session_set_id') <> 'string'
      OR jsonb_typeof(item->'source_template_set_id') NOT IN ('string','null')
      OR jsonb_typeof(item->'suggested_weight_unit') NOT IN ('string','null')
     THEN PERFORM usc_fail('Invalid snapshot set'); END IF;
     FOREACH field IN ARRAY ARRAY['set_number','rest_seconds','target_reps','target_duration_seconds'] LOOP
       IF jsonb_typeof(item->field) <> 'null' AND
          (jsonb_typeof(item->field) <> 'number' OR (item->>field) !~ '^[0-9]+$')
       THEN PERFORM usc_fail('Invalid integer snapshot measurement'); END IF;
     END LOOP;
     FOREACH field IN ARRAY ARRAY['target_distance_meters','suggested_weight'] LOOP
       IF jsonb_typeof(item->field) <> 'null' THEN
         value := item->>field;
         IF jsonb_typeof(item->field) <> 'string' OR value !~ '^[0-9]+(\.[0-9]{1,3})?$'
         THEN PERFORM usc_fail('Snapshot decimals must be decimal strings with at most three places'); END IF;
         item := jsonb_set(item, ARRAY[field], to_jsonb((value::numeric(12,3))::text));
       END IF;
     END LOOP;
     normalized_sets := normalized_sets || jsonb_build_array(item);
   END LOOP;
   normalized_ex := jsonb_set(ex, '{sets}', normalized_sets);
   exercises_result := exercises_result || jsonb_build_array(normalized_ex);
 END LOOP;
 result := jsonb_set(document, '{exercises}', exercises_result);
 RETURN result;
END $$;

CREATE FUNCTION usc_historical_uuid(kind text, identifier uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT CASE kind
 WHEN 'exercises' THEN EXISTS (SELECT FROM session_exercises WHERE exercise_id_snapshot=identifier)
   OR EXISTS (SELECT FROM workout_sessions w, jsonb_array_elements(w.starting_plan_snapshot->'exercises') e WHERE e->>'exercise_id'=identifier::text)
 WHEN 'workout_templates' THEN EXISTS (SELECT FROM workout_sessions WHERE source_template_id_snapshot=identifier OR applied_template_id_snapshot=identifier)
   OR EXISTS (SELECT FROM workout_templates WHERE copied_from_template_id_snapshot=identifier)
 WHEN 'template_exercises' THEN EXISTS (SELECT FROM session_exercises WHERE source_template_exercise_id_snapshot=identifier)
   OR EXISTS (SELECT FROM workout_sessions w, jsonb_array_elements(w.starting_plan_snapshot->'exercises') e WHERE e->>'source_template_exercise_id'=identifier::text)
 WHEN 'template_sets' THEN EXISTS (SELECT FROM session_sets WHERE source_template_set_id_snapshot=identifier)
   OR EXISTS (SELECT FROM workout_sessions w, jsonb_array_elements(w.starting_plan_snapshot->'exercises') e,
     jsonb_array_elements(e->'sets') s WHERE s->>'source_template_set_id'=identifier::text)
 WHEN 'session_exercises' THEN EXISTS (SELECT FROM workout_sessions w, jsonb_array_elements(w.starting_plan_snapshot->'exercises') e WHERE e->>'session_exercise_id'=identifier::text)
 WHEN 'session_sets' THEN EXISTS (SELECT FROM workout_sessions w, jsonb_array_elements(w.starting_plan_snapshot->'exercises') e,
     jsonb_array_elements(e->'sets') s WHERE s->>'session_set_id'=identifier::text)
 ELSE false END
$$;

CREATE FUNCTION usc_write_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n jsonb; o jsonb; parent workout_sessions; entry session_exercises;
 catalog record; source workout_templates; target workout_templates; source_entry template_exercises;
 source_set template_sets; field text; is_initial boolean;
BEGIN
 -- One transaction lock serializes this initial local foundation's guarded writes.
 -- It prevents cross-table write skew; optimize only with equivalent concurrency tests.
 PERFORM pg_advisory_xact_lock(746231901);
 IF TG_OP='DELETE' THEN
   IF TG_TABLE_NAME IN ('workout_sessions','session_exercises') THEN
     PERFORM usc_fail('Session history and captured exercise parents cannot be deleted');
   END IF;
   IF TG_TABLE_NAME='session_sets' THEN
     SELECT w.* INTO parent FROM workout_sessions w JOIN session_exercises e ON e.session_id=w.id WHERE e.id=OLD.session_exercise_id;
     IF parent.status <> 'in_progress' OR OLD.status='completed'
        OR OLD.actual_reps IS NOT NULL OR OLD.actual_duration_seconds IS NOT NULL
        OR OLD.actual_distance_meters IS NOT NULL OR OLD.actual_weight IS NOT NULL
        OR OLD.completed_at IS NOT NULL OR OLD.rest_started_at IS NOT NULL OR OLD.rest_ended_at IS NOT NULL
     THEN PERFORM usc_fail('Only an unperformed set in an active session may be removed'); END IF;
   END IF;
   RETURN OLD;
 END IF;
 n := to_jsonb(NEW);
 IF TG_OP='UPDATE' THEN
   o := to_jsonb(OLD);
   IF (n->'id') IS DISTINCT FROM (o->'id') OR (n->'exercise_id') IS DISTINCT FROM (o->'exercise_id')
        AND TG_TABLE_NAME IN ('provider_exercises','custom_exercises')
   THEN PERFORM usc_fail('Primary keys are immutable'); END IF;
   IF n ? 'created_at' AND n->'created_at' IS DISTINCT FROM o->'created_at'
   THEN PERFORM usc_fail('Creation timestamps are immutable'); END IF;
 END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN ('exercises','workout_templates','template_exercises','template_sets','session_exercises','session_sets') THEN
   IF usc_historical_uuid(TG_TABLE_NAME,(n->>'id')::uuid)
   THEN PERFORM usc_fail('An identifier retained by history cannot be reused'); END IF;
 END IF;
 IF n ? 'created_at' AND TG_OP='INSERT' THEN n := jsonb_set(n,'{created_at}',to_jsonb(statement_timestamp())); END IF;
 IF n ? 'updated_at' THEN n := jsonb_set(n,'{updated_at}',to_jsonb(statement_timestamp())); END IF;

 IF TG_TABLE_NAME='workout_templates' THEN
   IF TG_OP='INSERT' THEN
     IF NEW.copied_from_template_id_snapshot IS DISTINCT FROM NEW.copied_from_template_id
     THEN PERFORM usc_fail('Copy provenance requires a real live source'); END IF;
   ELSE
     IF NEW.copied_from_template_id_snapshot IS DISTINCT FROM OLD.copied_from_template_id_snapshot
        OR OLD.copied_from_template_id IS NULL AND NEW.copied_from_template_id IS NOT NULL
     THEN PERFORM usc_fail('Copy provenance cannot be replaced or reattached'); END IF;
     IF NEW.version < OLD.version OR NEW.version > OLD.version+1 THEN PERFORM usc_fail('Template version must advance one step'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='workout_sessions' THEN
   IF TG_OP='INSERT' THEN
     IF NEW.status <> 'in_progress' OR NEW.starting_plan_snapshot IS NOT NULL
     THEN PERFORM usc_fail('Start an active session with an open atomic capture'); END IF;
     IF NEW.source_template_id_snapshot IS DISTINCT FROM NEW.source_template_id
     THEN PERFORM usc_fail('Initial source identity requires its live template'); END IF;
     IF NEW.source_template_id IS NOT NULL THEN
       SELECT * INTO source FROM workout_templates WHERE id=NEW.source_template_id FOR UPDATE;
       IF NOT FOUND OR NEW.source_template_type_snapshot IS DISTINCT FROM source.template_type
          OR NEW.source_template_version IS DISTINCT FROM source.version
          OR source.template_type='personal' AND source.owner_user_id <> NEW.user_id
       THEN PERFORM usc_fail('Invalid initial template source/owner/version'); END IF;
     END IF;
   ELSE
     FOREACH field IN ARRAY ARRAY['user_id','source_template_id_snapshot','source_template_type_snapshot','source_template_version','name_snapshot','started_at'] LOOP
       IF n->field IS DISTINCT FROM o->field THEN PERFORM usc_fail('Captured session identity is immutable'); END IF;
     END LOOP;
     IF OLD.status <> 'in_progress' AND NEW.status IS DISTINCT FROM OLD.status
     THEN PERFORM usc_fail('Terminal session state cannot rewind'); END IF;
     IF OLD.finished_at IS NOT NULL AND NEW.finished_at IS DISTINCT FROM OLD.finished_at
     THEN PERFORM usc_fail('Terminal session time is immutable'); END IF;
     IF OLD.starting_plan_snapshot IS NOT NULL AND NEW.starting_plan_snapshot IS DISTINCT FROM OLD.starting_plan_snapshot
     THEN PERFORM usc_fail('The starting plan cannot be edited or capture reopened'); END IF;
     IF OLD.starting_plan_snapshot IS NULL AND NEW.starting_plan_snapshot IS NOT NULL THEN
       IF EXISTS (SELECT FROM session_sets s JOIN session_exercises e ON e.id=s.session_exercise_id
          WHERE e.session_id=NEW.id AND (s.status <> 'pending' OR s.actual_reps IS NOT NULL
           OR s.actual_duration_seconds IS NOT NULL OR s.actual_distance_meters IS NOT NULL OR s.actual_weight IS NOT NULL))
       THEN PERFORM usc_fail('Initial capture cannot already contain performed sets'); END IF;
       IF usc_normalize_snapshot(NEW.starting_plan_snapshot) IS DISTINCT FROM usc_snapshot(to_jsonb(NEW))
       THEN PERFORM usc_fail('Starting snapshot does not match the complete initial plan'); END IF;
     END IF;
     IF OLD.source_template_id IS NULL AND NEW.source_template_id IS NOT NULL
     THEN PERFORM usc_fail('Deleted live sources cannot be reattached'); END IF;
     IF OLD.applied_template_id IS NULL AND OLD.applied_template_id_snapshot IS NOT NULL AND NEW.applied_template_id IS NOT NULL
     THEN PERFORM usc_fail('Deleted applied targets cannot be reattached'); END IF;
     IF OLD.template_update_requested IS NOT NULL AND NEW.template_update_requested IS DISTINCT FROM OLD.template_update_requested
     THEN PERFORM usc_fail('The recorded template-update answer cannot change'); END IF;
     IF OLD.template_update_status IN ('applied','declined','conflict') AND
        (NEW.template_update_status IS DISTINCT FROM OLD.template_update_status
        OR NEW.applied_template_id_snapshot IS DISTINCT FROM OLD.applied_template_id_snapshot
        OR NEW.template_updated_at IS DISTINCT FROM OLD.template_updated_at)
     THEN PERFORM usc_fail('A recorded optional-update result is immutable'); END IF;
   END IF;
   IF NEW.template_update_status='applied' AND (TG_OP='INSERT' OR OLD.template_update_status <> 'applied') THEN
     SELECT * INTO source FROM workout_templates WHERE id=NEW.source_template_id FOR UPDATE;
     SELECT * INTO target FROM workout_templates WHERE id=NEW.applied_template_id FOR UPDATE;
     IF source.id IS NULL OR target.id IS NULL OR target.template_type <> 'personal'
       OR target.owner_user_id <> NEW.user_id
       OR target.id IS DISTINCT FROM NEW.applied_template_id_snapshot
       OR source.template_type IS DISTINCT FROM NEW.source_template_type_snapshot
       OR source.template_type='personal' AND (target.id <> NEW.source_template_id_snapshot
           OR source.version NOT IN (NEW.source_template_version, NEW.source_template_version+1))
       OR source.template_type='sample' AND (source.version <> NEW.source_template_version
           OR target.copied_from_template_id_snapshot IS DISTINCT FROM NEW.source_template_id_snapshot)
     THEN PERFORM usc_fail('Invalid optional-update ownership, source version or copy lineage'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='session_exercises' THEN
   SELECT * INTO parent FROM workout_sessions WHERE id=NEW.session_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF parent.status <> 'in_progress' THEN PERFORM usc_fail('Cannot add to a terminal session'); END IF;
     SELECT e.*, c.name AS category_name,c.measurement_kind,b.name AS body_name,x.created_by_user_id
       INTO catalog FROM exercises e JOIN exercise_categories c ON c.id=e.category_id
       JOIN body_parts b ON b.id=e.body_part_id LEFT JOIN custom_exercises x ON x.exercise_id=e.id WHERE e.id=NEW.exercise_id;
     IF catalog.id IS NULL OR NEW.exercise_id_snapshot IS DISTINCT FROM NEW.exercise_id
       OR NEW.exercise_source_type_snapshot IS DISTINCT FROM catalog.source_type
       OR NEW.name_snapshot IS DISTINCT FROM catalog.name OR NEW.category_snapshot IS DISTINCT FROM catalog.category_name
       OR NEW.body_part_snapshot IS DISTINCT FROM catalog.body_name
       OR NEW.measurement_kind_snapshot IS DISTINCT FROM catalog.measurement_kind
       OR catalog.source_type='custom' AND catalog.created_by_user_id IS DISTINCT FROM parent.user_id
     THEN PERFORM usc_fail('Invalid captured exercise classification or ownership'); END IF;
     IF NEW.source_template_exercise_id_snapshot IS DISTINCT FROM NEW.source_template_exercise_id
     THEN PERFORM usc_fail('Captured entry lineage requires a live source'); END IF;
     IF NEW.source_template_exercise_id IS NOT NULL THEN
       SELECT * INTO source_entry FROM template_exercises WHERE id=NEW.source_template_exercise_id;
       IF parent.starting_plan_snapshot IS NOT NULL OR source_entry.template_id IS DISTINCT FROM parent.source_template_id
          OR source_entry.exercise_id IS DISTINCT FROM NEW.exercise_id
       THEN PERFORM usc_fail('Wrong template exercise lineage'); END IF;
     END IF;
   ELSE
     IF (n - ARRAY['updated_at','exercise_id','source_template_exercise_id','notes'])
       IS DISTINCT FROM (o - ARRAY['updated_at','exercise_id','source_template_exercise_id','notes'])
     THEN PERFORM usc_fail('Session exercise snapshots and order are immutable'); END IF;
     IF (OLD.exercise_id IS NULL AND NEW.exercise_id IS NOT NULL)
       OR (OLD.source_template_exercise_id IS NULL AND NEW.source_template_exercise_id IS NOT NULL)
     THEN PERFORM usc_fail('Deleted sources cannot be reattached'); END IF;
     IF parent.status <> 'in_progress' AND NEW.notes IS DISTINCT FROM OLD.notes
     THEN PERFORM usc_fail('Terminal history cannot be edited'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='session_sets' THEN
   SELECT * INTO entry FROM session_exercises WHERE id=NEW.session_exercise_id;
   SELECT * INTO parent FROM workout_sessions WHERE id=entry.session_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF parent.status <> 'in_progress' THEN PERFORM usc_fail('Cannot add sets to terminal history'); END IF;
     IF NEW.status <> 'pending' OR NEW.actual_reps IS NOT NULL OR NEW.actual_duration_seconds IS NOT NULL
       OR NEW.actual_distance_meters IS NOT NULL OR NEW.actual_weight IS NOT NULL
     THEN PERFORM usc_fail('New sets must begin pending and unperformed'); END IF;
     is_initial := parent.starting_plan_snapshot IS NULL;
     IF NEW.was_in_starting_plan IS DISTINCT FROM is_initial
     THEN PERFORM usc_fail('Initial membership must match the atomic capture phase'); END IF;
     IF NOT is_initial AND EXISTS (
       SELECT FROM jsonb_array_elements(parent.starting_plan_snapshot->'exercises') e,
        jsonb_array_elements(e->'sets') s WHERE e->>'session_exercise_id'=entry.id::text
        AND ((s->>'set_number')::integer=NEW.set_number OR s->>'session_set_id'=NEW.id::text))
     THEN PERFORM usc_fail('An initial set identity/number cannot be reused'); END IF;
     IF NOT is_initial AND NEW.set_number <= GREATEST(
       COALESCE((SELECT max(s.set_number) FROM session_sets s WHERE s.session_exercise_id=entry.id),0),
       COALESCE((SELECT max((s->>'set_number')::integer) FROM jsonb_array_elements(parent.starting_plan_snapshot->'exercises') e,
          jsonb_array_elements(e->'sets') s WHERE e->>'session_exercise_id'=entry.id::text),0))
     THEN PERFORM usc_fail('New sets must follow retained initial/existing set numbers'); END IF;
     IF NEW.source_template_set_id_snapshot IS DISTINCT FROM NEW.source_template_set_id
     THEN PERFORM usc_fail('Captured set lineage requires its live planned source'); END IF;
     IF NEW.source_template_set_id IS NOT NULL THEN
       SELECT * INTO source_set FROM template_sets WHERE id=NEW.source_template_set_id;
       IF source_set.template_exercise_id IS DISTINCT FROM entry.source_template_exercise_id
         OR NEW.target_reps_snapshot IS DISTINCT FROM source_set.target_reps
         OR NEW.target_duration_seconds_snapshot IS DISTINCT FROM source_set.target_duration_seconds
         OR NEW.target_distance_meters_snapshot IS DISTINCT FROM source_set.target_distance_meters
         OR NEW.suggested_weight_snapshot IS DISTINCT FROM source_set.suggested_weight
         OR NEW.suggested_weight_unit_snapshot IS DISTINCT FROM source_set.weight_unit
         OR NEW.rest_seconds IS DISTINCT FROM source_set.rest_seconds
       THEN PERFORM usc_fail('Wrong planned-set lineage or starting targets'); END IF;
     END IF;
   ELSE
     FOREACH field IN ARRAY ARRAY['session_exercise_id','source_template_set_id_snapshot','set_number','target_reps_snapshot',
       'target_duration_seconds_snapshot','target_distance_meters_snapshot','suggested_weight_snapshot','suggested_weight_unit_snapshot','was_in_starting_plan'] LOOP
       IF n->field IS DISTINCT FROM o->field THEN PERFORM usc_fail('Original set identity and targets are immutable'); END IF;
     END LOOP;
     IF OLD.source_template_set_id IS NULL AND NEW.source_template_set_id IS NOT NULL
     THEN PERFORM usc_fail('Deleted set sources cannot be reattached'); END IF;
     IF OLD.status='completed' OR parent.status <> 'in_progress' THEN
       IF (n - ARRAY['updated_at','source_template_set_id']) IS DISTINCT FROM (o - ARRAY['updated_at','source_template_set_id'])
       THEN PERFORM usc_fail('Completed/terminal performance and event times are immutable'); END IF;
     END IF;
   END IF;
 END IF;
 NEW := jsonb_populate_record(NEW,n);
 RETURN NEW;
END $$;

CREATE FUNCTION usc_validate_database() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (
   SELECT FROM exercises e LEFT JOIN provider_exercises p ON p.exercise_id=e.id LEFT JOIN custom_exercises c ON c.exercise_id=e.id
   WHERE (e.source_type='provider' AND (p.exercise_id IS NULL OR c.exercise_id IS NOT NULL))
      OR (e.source_type='custom' AND (c.exercise_id IS NULL OR p.exercise_id IS NOT NULL)))
 THEN PERFORM usc_fail('Each exercise requires exactly its matching subtype'); END IF;
 IF EXISTS (
   SELECT FROM template_exercises t JOIN workout_templates w ON w.id=t.template_id
    JOIN exercises e ON e.id=t.exercise_id LEFT JOIN custom_exercises c ON c.exercise_id=e.id
   WHERE e.source_type='custom' AND (w.template_type='sample' OR c.created_by_user_id IS DISTINCT FROM w.owner_user_id))
 THEN PERFORM usc_fail('A template cannot use another owner private exercise or custom sample exercise'); END IF;
 IF EXISTS (
   SELECT FROM session_exercises s JOIN workout_sessions w ON w.id=s.session_id JOIN exercises e ON e.id=s.exercise_id
    LEFT JOIN custom_exercises c ON c.exercise_id=e.id
   WHERE e.source_type IS DISTINCT FROM s.exercise_source_type_snapshot
      OR (e.source_type='custom' AND c.created_by_user_id IS DISTINCT FROM w.user_id))
 THEN PERFORM usc_fail('Session custom exercise ownership/source mismatch'); END IF;
 IF EXISTS (
   SELECT FROM template_sets s JOIN template_exercises t ON t.id=s.template_exercise_id
   JOIN exercises e ON e.id=t.exercise_id JOIN exercise_categories c ON c.id=e.category_id
   WHERE NOT usc_measurement(c.measurement_kind,s.target_reps,s.target_duration_seconds,s.target_distance_meters,false))
 THEN PERFORM usc_fail('Template measurements do not match category kind'); END IF;
 IF EXISTS (
   SELECT FROM session_sets s JOIN session_exercises e ON e.id=s.session_exercise_id
   JOIN workout_sessions w ON w.id=e.session_id
   WHERE NOT usc_measurement(e.measurement_kind_snapshot,s.target_reps_snapshot,s.target_duration_seconds_snapshot,s.target_distance_meters_snapshot,false)
      OR NOT usc_measurement(e.measurement_kind_snapshot,s.actual_reps,s.actual_duration_seconds,s.actual_distance_meters,s.status='completed')
      OR s.completed_at < w.started_at OR s.completed_at > w.finished_at
      OR s.rest_started_at < w.started_at OR s.rest_started_at > w.finished_at
      OR s.rest_ended_at > w.finished_at)
 THEN PERFORM usc_fail('Invalid session measurement or cross-table event chronology'); END IF;
 IF EXISTS (SELECT FROM workout_sessions WHERE starting_plan_snapshot IS NULL)
 THEN PERFORM usc_fail('Atomic starting-plan capture must be sealed before commit'); END IF;
 -- Live links may detach only after the exact source disappears.
 IF EXISTS (SELECT FROM workout_templates w WHERE
    w.copied_from_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM workout_templates t WHERE t.id=w.copied_from_template_id_snapshot) THEN w.copied_from_template_id_snapshot END)
 OR EXISTS (SELECT FROM workout_templates w JOIN workout_templates s ON s.id=w.copied_from_template_id WHERE w.template_type <> 'personal' OR s.template_type='personal' AND s.owner_user_id IS DISTINCT FROM w.owner_user_id)
 THEN PERFORM usc_fail('Copy source/owner detachment is invalid'); END IF;
 IF EXISTS (SELECT FROM workout_sessions w WHERE
   w.source_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM workout_templates t WHERE t.id=w.source_template_id_snapshot) THEN w.source_template_id_snapshot END
   OR w.applied_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM workout_templates t WHERE t.id=w.applied_template_id_snapshot) THEN w.applied_template_id_snapshot END)
 OR EXISTS (SELECT FROM workout_sessions w JOIN workout_templates t ON t.id=w.source_template_id
   WHERE t.template_type IS DISTINCT FROM w.source_template_type_snapshot OR t.template_type='personal' AND t.owner_user_id IS DISTINCT FROM w.user_id)
 OR EXISTS (SELECT FROM workout_sessions w JOIN workout_templates t ON t.id=w.applied_template_id
   WHERE t.template_type <> 'personal' OR t.owner_user_id IS DISTINCT FROM w.user_id
     OR w.source_template_type_snapshot='personal' AND t.id IS DISTINCT FROM w.source_template_id_snapshot
     OR w.source_template_type_snapshot='sample' AND t.copied_from_template_id_snapshot IS DISTINCT FROM w.source_template_id_snapshot)
 THEN PERFORM usc_fail('Session source or applied-target lineage is invalid'); END IF;
 IF EXISTS (SELECT FROM session_exercises e JOIN workout_sessions w ON w.id=e.session_id WHERE
   e.exercise_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM exercises x WHERE x.id=e.exercise_id_snapshot) THEN e.exercise_id_snapshot END
   OR e.source_template_exercise_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM template_exercises t WHERE t.id=e.source_template_exercise_id_snapshot) THEN e.source_template_exercise_id_snapshot END)
 OR EXISTS (SELECT FROM session_exercises e JOIN workout_sessions w ON w.id=e.session_id JOIN template_exercises t ON t.id=e.source_template_exercise_id
    WHERE t.template_id IS DISTINCT FROM w.source_template_id_snapshot OR t.exercise_id IS DISTINCT FROM e.exercise_id_snapshot)
 OR EXISTS (SELECT FROM session_sets s WHERE s.source_template_set_id IS DISTINCT FROM
    CASE WHEN EXISTS(SELECT FROM template_sets t WHERE t.id=s.source_template_set_id_snapshot) THEN s.source_template_set_id_snapshot END)
 OR EXISTS (SELECT FROM session_sets s JOIN session_exercises e ON e.id=s.session_exercise_id
    JOIN template_sets t ON t.id=s.source_template_set_id WHERE t.template_exercise_id IS DISTINCT FROM e.source_template_exercise_id_snapshot)
 THEN PERFORM usc_fail('Historical live link or source chain is invalid'); END IF;
 IF EXISTS (SELECT FROM provider_exercises p,
   LATERAL jsonb_array_elements(COALESCE(p.instructions,'[]')||COALESCE(p.target_muscles,'[]')||COALESCE(p.secondary_muscles,'[]')) v
   WHERE jsonb_typeof(v) <> 'string')
 OR EXISTS (SELECT FROM provider_exercises p, LATERAL jsonb_array_elements(COALESCE(p.media_references,'[]')) v WHERE jsonb_typeof(v) <> 'object')
 THEN PERFORM usc_fail('Provider JSON arrays contain invalid element types'); END IF;
 RETURN NULL;
END $$;

CREATE TRIGGER usc_before_users BEFORE INSERT OR UPDATE OR DELETE ON users FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_users AFTER INSERT OR UPDATE OR DELETE ON users DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_user_identities BEFORE INSERT OR UPDATE OR DELETE ON user_identities FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_user_identities AFTER INSERT OR UPDATE OR DELETE ON user_identities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_exercise_categories BEFORE INSERT OR UPDATE OR DELETE ON exercise_categories FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_exercise_categories AFTER INSERT OR UPDATE OR DELETE ON exercise_categories DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_body_parts BEFORE INSERT OR UPDATE OR DELETE ON body_parts FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_body_parts AFTER INSERT OR UPDATE OR DELETE ON body_parts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_exercises BEFORE INSERT OR UPDATE OR DELETE ON exercises FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_exercises AFTER INSERT OR UPDATE OR DELETE ON exercises DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_provider_exercises BEFORE INSERT OR UPDATE OR DELETE ON provider_exercises FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_provider_exercises AFTER INSERT OR UPDATE OR DELETE ON provider_exercises DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_custom_exercises BEFORE INSERT OR UPDATE OR DELETE ON custom_exercises FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_custom_exercises AFTER INSERT OR UPDATE OR DELETE ON custom_exercises DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_workout_templates BEFORE INSERT OR UPDATE OR DELETE ON workout_templates FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_workout_templates AFTER INSERT OR UPDATE OR DELETE ON workout_templates DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_template_exercises BEFORE INSERT OR UPDATE OR DELETE ON template_exercises FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_template_exercises AFTER INSERT OR UPDATE OR DELETE ON template_exercises DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_template_sets BEFORE INSERT OR UPDATE OR DELETE ON template_sets FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_template_sets AFTER INSERT OR UPDATE OR DELETE ON template_sets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_workout_sessions BEFORE INSERT OR UPDATE OR DELETE ON workout_sessions FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_workout_sessions AFTER INSERT OR UPDATE OR DELETE ON workout_sessions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_session_exercises BEFORE INSERT OR UPDATE OR DELETE ON session_exercises FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_session_exercises AFTER INSERT OR UPDATE OR DELETE ON session_exercises DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();
CREATE TRIGGER usc_before_session_sets BEFORE INSERT OR UPDATE OR DELETE ON session_sets FOR EACH ROW EXECUTE FUNCTION usc_write_guard();
CREATE CONSTRAINT TRIGGER usc_deferred_session_sets AFTER INSERT OR UPDATE OR DELETE ON session_sets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION usc_validate_database();


CREATE FUNCTION usc_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM usc_fail('TRUNCATE is not a history-safe foundation operation'); RETURN NULL; END $$;
CREATE TRIGGER usc_no_truncate_users BEFORE TRUNCATE ON users FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_user_identities BEFORE TRUNCATE ON user_identities FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_exercise_categories BEFORE TRUNCATE ON exercise_categories FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_body_parts BEFORE TRUNCATE ON body_parts FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_exercises BEFORE TRUNCATE ON exercises FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_provider_exercises BEFORE TRUNCATE ON provider_exercises FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_custom_exercises BEFORE TRUNCATE ON custom_exercises FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_workout_templates BEFORE TRUNCATE ON workout_templates FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_template_exercises BEFORE TRUNCATE ON template_exercises FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_template_sets BEFORE TRUNCATE ON template_sets FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_workout_sessions BEFORE TRUNCATE ON workout_sessions FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_session_exercises BEFORE TRUNCATE ON session_exercises FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
CREATE TRIGGER usc_no_truncate_session_sets BEFORE TRUNCATE ON session_sets FOR EACH STATEMENT EXECUTE FUNCTION usc_no_truncate();
