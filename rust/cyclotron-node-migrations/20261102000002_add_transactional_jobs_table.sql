-- Transactional email gets its own heap, so a broadcast-sized backlog on
-- cyclotron_jobs cannot bloat the table its dequeue reads, and autovacuum on one
-- lane never paces the other. Same database, so moving a row between the two
-- stays a single statement that keeps the lock_id guard.
--
-- Columns mirror cyclotron_jobs as of 20260813000001. The status enum is a
-- database type and is reused rather than redeclared.
CREATE TABLE IF NOT EXISTS cyclotron_jobs_transactional (
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
    state BYTEA,
    distinct_id TEXT,
    person_id TEXT,
    action_id TEXT,
    dequeue_seq BIGINT,
    cancel_requested_at TIMESTAMPTZ
);

-- No queue_name predicate on the dequeue index: the whole table is one lane, so
-- every available row is a candidate. priority leads to match the worker's
-- shared ORDER BY, and scheduled trails so `scheduled <= NOW()` stays an Index
-- Cond rather than a heap-level filter.
CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_fair_dequeue
    ON cyclotron_jobs_transactional (priority, dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available';

CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_stalled
    ON cyclotron_jobs_transactional (last_heartbeat)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_terminal
    ON cyclotron_jobs_transactional (last_transition)
    WHERE status IN ('completed', 'failed', 'canceled');

CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_team_id
    ON cyclotron_jobs_transactional (team_id);

CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_function_id
    ON cyclotron_jobs_transactional (function_id);

-- Mirrors idx_cyclotron_jobs_action_reschedule: the timing-edit sweep runs
-- against both tables.
CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_action_reschedule
    ON cyclotron_jobs_transactional (function_id, action_id, scheduled)
    WHERE status = 'available';

-- The subscription matcher and the step-resume lookups read both tables.
CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_distinct_id
    ON cyclotron_jobs_transactional (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_transactional_person_id
    ON cyclotron_jobs_transactional (team_id, person_id)
    WHERE person_id IS NOT NULL;
