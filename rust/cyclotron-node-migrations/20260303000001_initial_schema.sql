CREATE TYPE CyclotronJobStatus AS ENUM(
    'available',
    'running',
    'completed',
    'failed',
    'canceled'
);

CREATE TABLE IF NOT EXISTS cyclotron_jobs (
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    function_id UUID,
    queue_name TEXT NOT NULL,
    status CyclotronJobStatus NOT NULL,
    priority SMALLINT NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    lock_id UUID,
    last_heartbeat TIMESTAMPTZ,
    janitor_touch_count SMALLINT NOT NULL DEFAULT 0,
    transition_count SMALLINT NOT NULL DEFAULT 0,
    last_transition TIMESTAMPTZ NOT NULL,
    parent_run_id TEXT,
    state BYTEA
);

-- Dequeue: workers SELECT available jobs ordered by priority then scheduled time
CREATE INDEX idx_cyclotron_jobs_dequeue
    ON cyclotron_jobs (queue_name, priority, scheduled)
    WHERE status = 'available';

-- Janitor: find running jobs with stale heartbeats
CREATE INDEX idx_cyclotron_jobs_stalled
    ON cyclotron_jobs (last_heartbeat)
    WHERE status = 'running';

-- Janitor: find terminal jobs to clean up
CREATE INDEX idx_cyclotron_jobs_terminal
    ON cyclotron_jobs (last_transition)
    WHERE status IN ('completed', 'failed', 'canceled');

CREATE INDEX idx_cyclotron_jobs_team_id ON cyclotron_jobs(team_id);
CREATE INDEX idx_cyclotron_jobs_function_id ON cyclotron_jobs(function_id);
