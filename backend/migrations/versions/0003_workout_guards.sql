-- Frozen issue #30 replacements; all unrelated 0001 behavior remains intact.
CREATE OR REPLACE FUNCTION public.usc_write_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE n jsonb; o jsonb; parent public.workout_sessions; entry public.session_exercises;
 catalog record; source public.workout_templates; target public.workout_templates; source_entry public.template_exercises;
 source_set public.template_sets; field text; is_initial boolean; discard_id text;
BEGIN
 PERFORM pg_advisory_xact_lock(746231901);
 IF TG_OP='DELETE' THEN
   -- A transaction-local value alone is insufficient: execution must also be
   -- under the SECURITY DEFINER function owner's identity and exact parent.
   discard_id := current_setting('usc.discard_session_id', true);
   IF TG_TABLE_NAME IN ('workout_sessions','session_exercises','session_sets')
      AND current_user = pg_get_userbyid((SELECT proowner FROM pg_proc
        WHERE oid='public.usc_discard_active_session(uuid,uuid,boolean)'::regprocedure))
      AND discard_id IS NOT NULL AND discard_id <> '' THEN
     IF TG_TABLE_NAME='workout_sessions' THEN
       parent := OLD;
     ELSIF TG_TABLE_NAME='session_exercises' THEN
       SELECT * INTO parent FROM public.workout_sessions WHERE id=OLD.session_id;
     ELSE
       SELECT w.* INTO parent FROM public.workout_sessions w JOIN public.session_exercises e
         ON e.session_id=w.id WHERE e.id=OLD.session_exercise_id;
     END IF;
     IF parent.id::text=discard_id AND parent.status='in_progress' THEN RETURN OLD; END IF;
   END IF;
   IF TG_TABLE_NAME IN ('workout_sessions','session_exercises') THEN
     PERFORM public.usc_fail('Session history and captured exercise parents cannot be deleted');
   END IF;
   IF TG_TABLE_NAME='session_sets' THEN
     SELECT w.* INTO parent FROM public.workout_sessions w JOIN public.session_exercises e ON e.session_id=w.id WHERE e.id=OLD.session_exercise_id;
     IF parent.status <> 'in_progress' OR OLD.status='completed'
        OR OLD.actual_reps IS NOT NULL OR OLD.actual_duration_seconds IS NOT NULL
        OR OLD.actual_distance_meters IS NOT NULL OR OLD.actual_weight IS NOT NULL
        OR OLD.completed_at IS NOT NULL OR OLD.rest_started_at IS NOT NULL OR OLD.rest_ended_at IS NOT NULL
     THEN PERFORM public.usc_fail('Only an unperformed set in an active session may be removed'); END IF;
   END IF;
   RETURN OLD;
 END IF;
 n := to_jsonb(NEW);
 IF TG_OP='UPDATE' THEN
   o := to_jsonb(OLD);
   IF (n->'id') IS DISTINCT FROM (o->'id') OR (n->'exercise_id') IS DISTINCT FROM (o->'exercise_id')
        AND TG_TABLE_NAME IN ('provider_exercises','custom_exercises')
   THEN PERFORM public.usc_fail('Primary keys are immutable'); END IF;
   IF n ? 'created_at' AND n->'created_at' IS DISTINCT FROM o->'created_at'
   THEN PERFORM public.usc_fail('Creation timestamps are immutable'); END IF;
 END IF;
 IF TG_OP='INSERT' AND TG_TABLE_NAME IN ('exercises','workout_templates','template_exercises','template_sets','session_exercises','session_sets') THEN
   IF public.usc_historical_uuid(TG_TABLE_NAME,(n->>'id')::uuid)
   THEN PERFORM public.usc_fail('An identifier retained by history cannot be reused'); END IF;
 END IF;
 IF n ? 'created_at' AND TG_OP='INSERT' THEN n := jsonb_set(n,'{created_at}',to_jsonb(statement_timestamp())); END IF;
 IF n ? 'updated_at' THEN n := jsonb_set(n,'{updated_at}',to_jsonb(statement_timestamp())); END IF;

 -- D2: saved targets are never silently reinterpreted.
 IF TG_TABLE_NAME='exercises' AND TG_OP='UPDATE' THEN
   IF NEW.measurement_kind IS DISTINCT FROM OLD.measurement_kind
      AND EXISTS (SELECT FROM public.template_exercises WHERE exercise_id=OLD.id)
   THEN PERFORM public.usc_fail('Remove live template references before changing exercise kind'); END IF;
 END IF;

 IF TG_TABLE_NAME='workout_templates' THEN
   IF TG_OP='INSERT' THEN
     IF NEW.copied_from_template_id_snapshot IS DISTINCT FROM NEW.copied_from_template_id
     THEN PERFORM public.usc_fail('Copy provenance requires a real live source'); END IF;
   ELSE
     IF NEW.copied_from_template_id_snapshot IS DISTINCT FROM OLD.copied_from_template_id_snapshot
        OR OLD.copied_from_template_id IS NULL AND NEW.copied_from_template_id IS NOT NULL
     THEN PERFORM public.usc_fail('Copy provenance cannot be replaced or reattached'); END IF;
     IF NEW.version < OLD.version OR NEW.version > OLD.version+1 THEN PERFORM public.usc_fail('Template version must advance one step'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='workout_sessions' THEN
   IF TG_OP='INSERT' THEN
     IF NEW.status <> 'in_progress' OR NEW.starting_plan_snapshot IS NOT NULL
     THEN PERFORM public.usc_fail('Start an active session with an open atomic capture'); END IF;
     IF NEW.source_template_id_snapshot IS DISTINCT FROM NEW.source_template_id
     THEN PERFORM public.usc_fail('Initial source identity requires its live template'); END IF;
     IF NEW.source_template_id IS NOT NULL THEN
       SELECT * INTO source FROM public.workout_templates WHERE id=NEW.source_template_id FOR UPDATE;
       IF NOT FOUND OR NEW.source_template_type_snapshot IS DISTINCT FROM source.template_type
          OR NEW.source_template_version IS DISTINCT FROM source.version
          OR source.template_type='personal' AND source.owner_user_id <> NEW.user_id
       THEN PERFORM public.usc_fail('Invalid initial template source/owner/version'); END IF;
     END IF;
   ELSE
     IF OLD.status='cancelled' AND
       (n - ARRAY['updated_at','source_template_id','applied_template_id']) IS DISTINCT FROM
       (o - ARRAY['updated_at','source_template_id','applied_template_id'])
     THEN PERFORM public.usc_fail('Saved partial workout history is immutable'); END IF;
     FOREACH field IN ARRAY ARRAY['user_id','source_template_id_snapshot','source_template_type_snapshot','source_template_version','name_snapshot','started_at'] LOOP
       IF n->field IS DISTINCT FROM o->field THEN PERFORM public.usc_fail('Captured session identity is immutable'); END IF;
     END LOOP;
     IF OLD.status <> 'in_progress' AND NEW.status IS DISTINCT FROM OLD.status
     THEN PERFORM public.usc_fail('Terminal session state cannot rewind'); END IF;
     IF OLD.finished_at IS NOT NULL AND NEW.finished_at IS DISTINCT FROM OLD.finished_at
     THEN PERFORM public.usc_fail('Terminal session time is immutable'); END IF;
     IF OLD.starting_plan_snapshot IS NOT NULL AND NEW.starting_plan_snapshot IS DISTINCT FROM OLD.starting_plan_snapshot
     THEN PERFORM public.usc_fail('The starting plan cannot be edited or capture reopened'); END IF;
     IF OLD.starting_plan_snapshot IS NULL AND NEW.starting_plan_snapshot IS NOT NULL THEN
       IF EXISTS (SELECT FROM public.session_sets s JOIN public.session_exercises e ON e.id=s.session_exercise_id
          WHERE e.session_id=NEW.id AND (s.status <> 'pending' OR s.actual_reps IS NOT NULL
           OR s.actual_duration_seconds IS NOT NULL OR s.actual_distance_meters IS NOT NULL OR s.actual_weight IS NOT NULL))
       THEN PERFORM public.usc_fail('Initial capture cannot already contain performed sets'); END IF;
       IF public.usc_normalize_snapshot(NEW.starting_plan_snapshot) IS DISTINCT FROM public.usc_snapshot(to_jsonb(NEW))
       THEN PERFORM public.usc_fail('Starting snapshot does not match the complete initial plan'); END IF;
     END IF;
     IF OLD.source_template_id IS NULL AND NEW.source_template_id IS NOT NULL
     THEN PERFORM public.usc_fail('Deleted live sources cannot be reattached'); END IF;
     IF OLD.applied_template_id IS NULL AND OLD.applied_template_id_snapshot IS NOT NULL AND NEW.applied_template_id IS NOT NULL
     THEN PERFORM public.usc_fail('Deleted applied targets cannot be reattached'); END IF;
     IF OLD.template_update_requested IS NOT NULL AND NEW.template_update_requested IS DISTINCT FROM OLD.template_update_requested
     THEN PERFORM public.usc_fail('The recorded template-update answer cannot change'); END IF;
     IF OLD.template_update_status IN ('applied','declined','conflict') AND
        (NEW.template_update_status IS DISTINCT FROM OLD.template_update_status
        OR NEW.applied_template_id_snapshot IS DISTINCT FROM OLD.applied_template_id_snapshot
        OR NEW.template_updated_at IS DISTINCT FROM OLD.template_updated_at)
     THEN PERFORM public.usc_fail('A recorded optional-update result is immutable'); END IF;
   END IF;
   IF NEW.template_update_status='applied' AND (TG_OP='INSERT' OR OLD.template_update_status <> 'applied') THEN
     SELECT * INTO source FROM public.workout_templates WHERE id=NEW.source_template_id FOR UPDATE;
     SELECT * INTO target FROM public.workout_templates WHERE id=NEW.applied_template_id FOR UPDATE;
     IF source.id IS NULL OR target.id IS NULL OR target.template_type <> 'personal'
       OR target.owner_user_id <> NEW.user_id OR target.id IS DISTINCT FROM NEW.applied_template_id_snapshot
       OR source.template_type IS DISTINCT FROM NEW.source_template_type_snapshot
       OR source.template_type='personal' AND (target.id <> NEW.source_template_id_snapshot
           OR source.version NOT IN (NEW.source_template_version, NEW.source_template_version+1))
       OR source.template_type='sample' AND (source.version <> NEW.source_template_version
           OR target.copied_from_template_id_snapshot IS DISTINCT FROM NEW.source_template_id_snapshot)
     THEN PERFORM public.usc_fail('Invalid optional-update ownership, source version or copy lineage'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='session_exercises' THEN
   SELECT * INTO parent FROM public.workout_sessions WHERE id=NEW.session_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF parent.status <> 'in_progress' THEN PERFORM public.usc_fail('Cannot add to a terminal session'); END IF;
     SELECT e.*, c.name AS category_name,b.name AS body_name,x.created_by_user_id
       INTO catalog FROM public.exercises e JOIN public.exercise_categories c ON c.id=e.category_id
       JOIN public.body_parts b ON b.id=e.body_part_id LEFT JOIN public.custom_exercises x ON x.exercise_id=e.id WHERE e.id=NEW.exercise_id;
     IF catalog.id IS NULL OR NEW.exercise_id_snapshot IS DISTINCT FROM NEW.exercise_id
       OR NEW.exercise_source_type_snapshot IS DISTINCT FROM catalog.source_type
       OR NEW.name_snapshot IS DISTINCT FROM catalog.name OR NEW.category_snapshot IS DISTINCT FROM catalog.category_name
       OR NEW.body_part_snapshot IS DISTINCT FROM catalog.body_name
       OR NEW.measurement_kind_snapshot IS DISTINCT FROM catalog.measurement_kind
       OR catalog.source_type='custom' AND catalog.created_by_user_id IS DISTINCT FROM parent.user_id
     THEN PERFORM public.usc_fail('Invalid captured exercise classification or ownership'); END IF;
     IF NEW.source_template_exercise_id_snapshot IS DISTINCT FROM NEW.source_template_exercise_id
     THEN PERFORM public.usc_fail('Captured entry lineage requires a live source'); END IF;
     IF NEW.source_template_exercise_id IS NOT NULL THEN
       SELECT * INTO source_entry FROM public.template_exercises WHERE id=NEW.source_template_exercise_id;
       IF parent.starting_plan_snapshot IS NOT NULL OR source_entry.template_id IS DISTINCT FROM parent.source_template_id
          OR source_entry.exercise_id IS DISTINCT FROM NEW.exercise_id
       THEN PERFORM public.usc_fail('Wrong template exercise lineage'); END IF;
     END IF;
   ELSE
     IF (n - ARRAY['updated_at','exercise_id','source_template_exercise_id','notes'])
       IS DISTINCT FROM (o - ARRAY['updated_at','exercise_id','source_template_exercise_id','notes'])
     THEN PERFORM public.usc_fail('Session exercise snapshots and order are immutable'); END IF;
     IF (OLD.exercise_id IS NULL AND NEW.exercise_id IS NOT NULL)
       OR (OLD.source_template_exercise_id IS NULL AND NEW.source_template_exercise_id IS NOT NULL)
     THEN PERFORM public.usc_fail('Deleted sources cannot be reattached'); END IF;
     IF parent.status <> 'in_progress' AND NEW.notes IS DISTINCT FROM OLD.notes
     THEN PERFORM public.usc_fail('Terminal history cannot be edited'); END IF;
   END IF;
 END IF;

 IF TG_TABLE_NAME='session_sets' THEN
   SELECT * INTO entry FROM public.session_exercises WHERE id=NEW.session_exercise_id;
   SELECT * INTO parent FROM public.workout_sessions WHERE id=entry.session_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF parent.status <> 'in_progress' THEN PERFORM public.usc_fail('Cannot add sets to terminal history'); END IF;
     IF NEW.status <> 'pending' OR NEW.actual_reps IS NOT NULL OR NEW.actual_duration_seconds IS NOT NULL
       OR NEW.actual_distance_meters IS NOT NULL OR NEW.actual_weight IS NOT NULL
     THEN PERFORM public.usc_fail('New sets must begin pending and unperformed'); END IF;
     is_initial := parent.starting_plan_snapshot IS NULL;
     IF NEW.was_in_starting_plan IS DISTINCT FROM is_initial
     THEN PERFORM public.usc_fail('Initial membership must match the atomic capture phase'); END IF;
     IF NOT is_initial AND EXISTS (
       SELECT FROM jsonb_array_elements(parent.starting_plan_snapshot->'exercises') e,
        jsonb_array_elements(e->'sets') s WHERE e->>'session_exercise_id'=entry.id::text
        AND ((s->>'set_number')::integer=NEW.set_number OR s->>'session_set_id'=NEW.id::text))
     THEN PERFORM public.usc_fail('An initial set identity/number cannot be reused'); END IF;
     IF NOT is_initial AND NEW.set_number <= GREATEST(
       COALESCE((SELECT max(s.set_number) FROM public.session_sets s WHERE s.session_exercise_id=entry.id),0),
       COALESCE((SELECT max((s->>'set_number')::integer) FROM jsonb_array_elements(parent.starting_plan_snapshot->'exercises') e,
          jsonb_array_elements(e->'sets') s WHERE e->>'session_exercise_id'=entry.id::text),0))
     THEN PERFORM public.usc_fail('New sets must follow retained initial/existing set numbers'); END IF;
     IF NEW.source_template_set_id_snapshot IS DISTINCT FROM NEW.source_template_set_id
     THEN PERFORM public.usc_fail('Captured set lineage requires its live planned source'); END IF;
     IF NEW.source_template_set_id IS NOT NULL THEN
       SELECT * INTO source_set FROM public.template_sets WHERE id=NEW.source_template_set_id;
       IF source_set.template_exercise_id IS DISTINCT FROM entry.source_template_exercise_id
         OR NEW.target_reps_snapshot IS DISTINCT FROM source_set.target_reps
         OR NEW.target_duration_seconds_snapshot IS DISTINCT FROM source_set.target_duration_seconds
         OR NEW.target_distance_meters_snapshot IS DISTINCT FROM source_set.target_distance_meters
         OR NEW.suggested_weight_snapshot IS DISTINCT FROM source_set.suggested_weight
         OR NEW.suggested_weight_unit_snapshot IS DISTINCT FROM source_set.weight_unit
         OR NEW.rest_seconds IS DISTINCT FROM source_set.rest_seconds
       THEN PERFORM public.usc_fail('Wrong planned-set lineage or starting targets'); END IF;
     END IF;
   ELSE
     FOREACH field IN ARRAY ARRAY['session_exercise_id','source_template_set_id_snapshot','set_number','target_reps_snapshot',
       'target_duration_seconds_snapshot','target_distance_meters_snapshot','suggested_weight_snapshot','suggested_weight_unit_snapshot','was_in_starting_plan'] LOOP
       IF n->field IS DISTINCT FROM o->field THEN PERFORM public.usc_fail('Original set identity and targets are immutable'); END IF;
     END LOOP;
     IF OLD.source_template_set_id IS NULL AND NEW.source_template_set_id IS NOT NULL
     THEN PERFORM public.usc_fail('Deleted set sources cannot be reattached'); END IF;
     IF OLD.status IN ('completed','cancelled') OR parent.status <> 'in_progress' THEN
       IF (n - ARRAY['updated_at','source_template_set_id']) IS DISTINCT FROM (o - ARRAY['updated_at','source_template_set_id'])
       THEN PERFORM public.usc_fail('Completed/terminal performance and event times are immutable'); END IF;
     END IF;
   END IF;
 END IF;
 NEW := jsonb_populate_record(NEW,n);
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.usc_validate_database() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
 IF EXISTS (
   SELECT FROM public.exercises e LEFT JOIN public.provider_exercises p ON p.exercise_id=e.id LEFT JOIN public.custom_exercises c ON c.exercise_id=e.id
   WHERE (e.source_type='provider' AND (p.exercise_id IS NULL OR c.exercise_id IS NOT NULL))
      OR (e.source_type='custom' AND (c.exercise_id IS NULL OR p.exercise_id IS NOT NULL)))
 THEN PERFORM public.usc_fail('Each exercise requires exactly its matching subtype'); END IF;
 IF EXISTS (
   SELECT FROM public.template_exercises t JOIN public.workout_templates w ON w.id=t.template_id
    JOIN public.exercises e ON e.id=t.exercise_id LEFT JOIN public.custom_exercises c ON c.exercise_id=e.id
   WHERE e.source_type='custom' AND (w.template_type='sample' OR c.created_by_user_id IS DISTINCT FROM w.owner_user_id))
 THEN PERFORM public.usc_fail('A template cannot use another owner private exercise or custom sample exercise'); END IF;
 IF EXISTS (
   SELECT FROM public.session_exercises s JOIN public.workout_sessions w ON w.id=s.session_id JOIN public.exercises e ON e.id=s.exercise_id
    LEFT JOIN public.custom_exercises c ON c.exercise_id=e.id
   WHERE e.source_type IS DISTINCT FROM s.exercise_source_type_snapshot
      OR (e.source_type='custom' AND c.created_by_user_id IS DISTINCT FROM w.user_id))
 THEN PERFORM public.usc_fail('Session custom exercise ownership/source mismatch'); END IF;
 IF EXISTS (SELECT FROM public.exercises e JOIN public.exercise_categories c ON c.id=e.category_id
   WHERE NOT CASE WHEN c.id=4 THEN e.measurement_kind IN ('reps','duration')
     ELSE e.measurement_kind=c.measurement_kind END)
 THEN PERFORM public.usc_fail('Exercise measurement kind is incompatible with category'); END IF;
 IF EXISTS (SELECT FROM public.workout_templates w WHERE NOT EXISTS
   (SELECT FROM public.template_exercises t WHERE t.template_id=w.id))
 OR EXISTS (SELECT FROM public.template_exercises t WHERE NOT EXISTS
   (SELECT FROM public.template_sets s WHERE s.template_exercise_id=t.id))
 THEN PERFORM public.usc_fail('A saved template needs exercises and at least one set per exercise'); END IF;
 IF EXISTS (
   SELECT FROM public.template_sets s JOIN public.template_exercises t ON t.id=s.template_exercise_id
   JOIN public.exercises e ON e.id=t.exercise_id
   WHERE NOT public.usc_measurement(e.measurement_kind,s.target_reps,s.target_duration_seconds,s.target_distance_meters,true))
 THEN PERFORM public.usc_fail('A saved template requires complete effective-kind targets'); END IF;
 IF EXISTS (SELECT FROM public.session_sets s JOIN public.session_exercises e ON e.id=s.session_exercise_id
   JOIN public.workout_sessions w ON w.id=e.session_id
   WHERE (w.status='cancelled' AND s.status='pending')
      OR (s.status='cancelled' AND w.status <> 'cancelled'))
 THEN PERFORM public.usc_fail('Cancelled sessions and sets must transition together'); END IF;
 IF EXISTS (
   SELECT FROM public.session_sets s JOIN public.session_exercises e ON e.id=s.session_exercise_id
   JOIN public.workout_sessions w ON w.id=e.session_id
   WHERE NOT public.usc_measurement(e.measurement_kind_snapshot,s.target_reps_snapshot,s.target_duration_seconds_snapshot,s.target_distance_meters_snapshot,false)
      OR NOT public.usc_measurement(e.measurement_kind_snapshot,s.actual_reps,s.actual_duration_seconds,s.actual_distance_meters,s.status='completed')
      OR s.completed_at < w.started_at OR s.completed_at > w.finished_at
      OR s.rest_started_at < w.started_at OR s.rest_started_at > w.finished_at
      OR s.rest_ended_at > w.finished_at)
 THEN PERFORM public.usc_fail('Invalid session measurement or cross-table event chronology'); END IF;
 IF EXISTS (SELECT FROM public.workout_sessions WHERE starting_plan_snapshot IS NULL)
 THEN PERFORM public.usc_fail('Atomic starting-plan capture must be sealed before commit'); END IF;
 IF EXISTS (SELECT FROM public.workout_templates w WHERE
    w.copied_from_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM public.workout_templates t WHERE t.id=w.copied_from_template_id_snapshot) THEN w.copied_from_template_id_snapshot END)
 OR EXISTS (SELECT FROM public.workout_templates w JOIN public.workout_templates s ON s.id=w.copied_from_template_id WHERE w.template_type <> 'personal' OR s.template_type='personal' AND s.owner_user_id IS DISTINCT FROM w.owner_user_id)
 THEN PERFORM public.usc_fail('Copy source/owner detachment is invalid'); END IF;
 IF EXISTS (SELECT FROM public.workout_sessions w WHERE
   w.source_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM public.workout_templates t WHERE t.id=w.source_template_id_snapshot) THEN w.source_template_id_snapshot END
   OR w.applied_template_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM public.workout_templates t WHERE t.id=w.applied_template_id_snapshot) THEN w.applied_template_id_snapshot END)
 OR EXISTS (SELECT FROM public.workout_sessions w JOIN public.workout_templates t ON t.id=w.source_template_id
   WHERE t.template_type IS DISTINCT FROM w.source_template_type_snapshot OR t.template_type='personal' AND t.owner_user_id IS DISTINCT FROM w.user_id)
 OR EXISTS (SELECT FROM public.workout_sessions w JOIN public.workout_templates t ON t.id=w.applied_template_id
   WHERE t.template_type <> 'personal' OR t.owner_user_id IS DISTINCT FROM w.user_id
     OR w.source_template_type_snapshot='personal' AND t.id IS DISTINCT FROM w.source_template_id_snapshot
     OR w.source_template_type_snapshot='sample' AND t.copied_from_template_id_snapshot IS DISTINCT FROM w.source_template_id_snapshot)
 THEN PERFORM public.usc_fail('Session source or applied-target lineage is invalid'); END IF;
 IF EXISTS (SELECT FROM public.session_exercises e JOIN public.workout_sessions w ON w.id=e.session_id WHERE
   e.exercise_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM public.exercises x WHERE x.id=e.exercise_id_snapshot) THEN e.exercise_id_snapshot END
   OR e.source_template_exercise_id IS DISTINCT FROM CASE WHEN EXISTS(SELECT FROM public.template_exercises t WHERE t.id=e.source_template_exercise_id_snapshot) THEN e.source_template_exercise_id_snapshot END)
 OR EXISTS (SELECT FROM public.session_exercises e JOIN public.workout_sessions w ON w.id=e.session_id JOIN public.template_exercises t ON t.id=e.source_template_exercise_id
    WHERE t.template_id IS DISTINCT FROM w.source_template_id_snapshot OR t.exercise_id IS DISTINCT FROM e.exercise_id_snapshot)
 OR EXISTS (SELECT FROM public.session_sets s WHERE s.source_template_set_id IS DISTINCT FROM
    CASE WHEN EXISTS(SELECT FROM public.template_sets t WHERE t.id=s.source_template_set_id_snapshot) THEN s.source_template_set_id_snapshot END)
 OR EXISTS (SELECT FROM public.session_sets s JOIN public.session_exercises e ON e.id=s.session_exercise_id
    JOIN public.template_sets t ON t.id=s.source_template_set_id WHERE t.template_exercise_id IS DISTINCT FROM e.source_template_exercise_id_snapshot)
 THEN PERFORM public.usc_fail('Historical live link or source chain is invalid'); END IF;
 IF EXISTS (SELECT FROM public.provider_exercises p,
   LATERAL jsonb_array_elements(COALESCE(p.instructions,'[]')||COALESCE(p.target_muscles,'[]')||COALESCE(p.secondary_muscles,'[]')) v
   WHERE jsonb_typeof(v) <> 'string')
 OR EXISTS (SELECT FROM public.provider_exercises p, LATERAL jsonb_array_elements(COALESCE(p.media_references,'[]')) v WHERE jsonb_typeof(v) <> 'object')
 THEN PERFORM public.usc_fail('Provider JSON arrays contain invalid element types'); END IF;
 RETURN NULL;
END $$;
