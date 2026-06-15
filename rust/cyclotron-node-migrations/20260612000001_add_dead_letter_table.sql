-- Dead-letter store for poison-pill jobs. The janitor moves the full job row
-- here (instead of failing + deleting it) so runs survive fleet-wide worker
-- outages and can be replayed into cyclotron_jobs once the fleet is healthy.
CREATE TABLE IF NOT EXISTS cyclotron_jobs_dead_letter (
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    function_id UUID,
    original_queue_name TEXT NOT NULL,
    -- The job's status when it was dead-lettered (always 'running' for poison
    -- pills today) plus its last heartbeat — kept for replay triage, e.g.
    -- re-queuing only genuinely stalled runs.
    original_status CyclotronJobStatus NOT NULL,
    priority SMALLINT NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    last_heartbeat TIMESTAMPTZ,
    janitor_touch_count SMALLINT NOT NULL,
    transition_count SMALLINT NOT NULL,
    last_transition TIMESTAMPTZ NOT NULL,
    parent_run_id TEXT,
    state BYTEA,
    distinct_id TEXT,
    person_id TEXT,
    action_id TEXT,
    reason TEXT NOT NULL,
    dlq_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cyclotron_jobs_dead_letter_dlq_time
    ON cyclotron_jobs_dead_letter (dlq_time);
