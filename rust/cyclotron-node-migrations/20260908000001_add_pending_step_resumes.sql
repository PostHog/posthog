ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS pending_step_resumes JSONB;

CREATE OR REPLACE FUNCTION apply_pending_workflow_step_resume()
RETURNS TRIGGER AS $$
DECLARE
    invocation JSONB;
    wait_key TEXT;
    resume JSONB;
BEGIN
    invocation := convert_from(NEW.state, 'UTF8')::jsonb;
    wait_key := invocation #>> '{state,currentAction,awaitingResume,key}';
    resume := NEW.pending_step_resumes -> wait_key;
    IF resume IS NOT NULL THEN
        IF invocation #>> '{state,currentAction,resumeResult,key}' IS DISTINCT FROM wait_key THEN
            invocation := jsonb_set(invocation, '{state,currentAction,resumeResult}', resume);
            NEW.state := convert_to(invocation::text, 'UTF8');
            NEW.scheduled := LEAST(NEW.scheduled, NOW());
        END IF;
        NEW.pending_step_resumes := NULLIF(NEW.pending_step_resumes - wait_key, '{}'::jsonb);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER apply_pending_workflow_step_resume
BEFORE UPDATE OF state, status, pending_step_resumes ON cyclotron_jobs
FOR EACH ROW
WHEN (NEW.status = 'available' AND NEW.state IS NOT NULL AND NEW.pending_step_resumes IS NOT NULL)
EXECUTE FUNCTION apply_pending_workflow_step_resume();
