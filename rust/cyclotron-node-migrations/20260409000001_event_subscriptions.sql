-- Event subscriptions for the wait_until_event workflow step.
-- A row represents one workflow invocation that is paused waiting for a specific event
-- (matching event_name + filters) to arrive for a specific person.
-- The cdp-events consumer queries this table when processing events and wakes
-- matched jobs by setting cyclotron_jobs.scheduled = NOW().

CREATE TABLE IF NOT EXISTS cyclotron_event_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES cyclotron_jobs(id) ON DELETE CASCADE,
    team_id INT NOT NULL,
    person_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    filters JSONB,
    bytecode JSONB,
    expires_at TIMESTAMPTZ NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hot path: cdp-events consumer looks up subscriptions for an incoming event by
-- (team_id, event_name, person_id). Most lookups will return zero rows.
CREATE INDEX idx_event_subs_lookup
    ON cyclotron_event_subscriptions (team_id, event_name, person_id);

-- Used by the handler to look up subscriptions for a specific job (e.g. to detect
-- whether the wait was matched or timed out, and to clean up on the timeout path).
CREATE INDEX idx_event_subs_job
    ON cyclotron_event_subscriptions (job_id);

-- Used by the janitor to clean up subscriptions whose window has elapsed but whose
-- jobs are still around (the ON DELETE CASCADE handles the common cleanup path).
CREATE INDEX idx_event_subs_expires
    ON cyclotron_event_subscriptions (expires_at);
