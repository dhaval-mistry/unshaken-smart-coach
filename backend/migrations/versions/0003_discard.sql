-- Narrow D1 deletion boundary. A future service must derive owner_id from an
-- authenticated principal. No application role receives EXECUTE in this story.
CREATE FUNCTION public.usc_discard_active_session(session_id uuid, owner_id uuid, confirmed boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $$
DECLARE workout public.workout_sessions; previous_gate text;
BEGIN
 previous_gate := current_setting('usc.discard_session_id', true);
 IF confirmed IS DISTINCT FROM true THEN
   PERFORM public.usc_fail('Explicit active-workout discard confirmation is required');
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(746231901);
 SELECT * INTO workout FROM public.workout_sessions
   WHERE id=session_id AND user_id=owner_id FOR UPDATE;
 IF NOT FOUND OR workout.status <> 'in_progress' THEN
   PERFORM public.usc_fail('Only the owner active workout can be discarded');
 END IF;
 -- The guard also verifies execution under this function owner's identity.
 PERFORM pg_catalog.set_config('usc.discard_session_id', session_id::text, true);
 DELETE FROM public.session_sets s WHERE s.session_exercise_id IN
   (SELECT e.id FROM public.session_exercises e WHERE e.session_id=workout.id);
 DELETE FROM public.session_exercises e WHERE e.session_id=workout.id;
 DELETE FROM public.workout_sessions WHERE id=workout.id;
 PERFORM pg_catalog.set_config('usc.discard_session_id', COALESCE(previous_gate,''), true);
EXCEPTION WHEN OTHERS THEN
 PERFORM pg_catalog.set_config('usc.discard_session_id', COALESCE(previous_gate,''), true);
 RAISE;
END $$;

-- PostgreSQL grants function execution to PUBLIC by default. Revoke it in the
-- same migration transaction; a later backend-role story may grant it narrowly.
REVOKE ALL ON FUNCTION public.usc_discard_active_session(uuid,uuid,boolean) FROM PUBLIC;

COMMENT ON FUNCTION public.usc_discard_active_session(uuid,uuid,boolean) IS
 'Owner-held primitive for confirmed, owner-matched, in-progress draft discard only.';
