-- The only supported deletion of performed draft rows. No auth/API is supplied:
-- a future trusted service must derive user_id from verified identity, not input.
CREATE FUNCTION usc_discard_active_session(session_id uuid, owner_id uuid, confirmed boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE workout public.workout_sessions; previous_gate text;
BEGIN
 previous_gate := current_setting('usc.discard_session_id', true);
 IF confirmed IS DISTINCT FROM true THEN
   PERFORM public.usc_fail('Explicit active-workout discard confirmation is required');
 END IF;
 PERFORM pg_advisory_xact_lock(746231901);
 SELECT * INTO workout FROM public.workout_sessions
   WHERE id=session_id AND user_id=owner_id FOR UPDATE;
 IF NOT FOUND OR workout.status <> 'in_progress' THEN
   PERFORM public.usc_fail('Only the owner active workout can be discarded');
 END IF;
 previous_gate := current_setting('usc.discard_session_id', true);
 -- The write guard requires both this exact parent and SECURITY DEFINER owner
 -- identity. Ordinary writers cannot authorize deletion just by setting a GUC.
 PERFORM set_config('usc.discard_session_id', session_id::text, true);
 DELETE FROM public.session_sets s WHERE s.session_exercise_id IN
   (SELECT e.id FROM public.session_exercises e WHERE e.session_id=workout.id);
 DELETE FROM public.session_exercises e WHERE e.session_id=workout.id;
 DELETE FROM public.workout_sessions WHERE id=workout.id;
 PERFORM set_config('usc.discard_session_id', COALESCE(previous_gate,''), true);
EXCEPTION WHEN OTHERS THEN
 -- Restore the caller's state even if it catches this statement in a savepoint.
 PERFORM set_config('usc.discard_session_id', COALESCE(previous_gate,''), true);
 RAISE;
END $$;
COMMENT ON FUNCTION usc_discard_active_session(uuid,uuid,boolean) IS
 'Trusted-service primitive: explicit confirmation, supplied verified owner, active-only atomic discard; never terminal history.';
