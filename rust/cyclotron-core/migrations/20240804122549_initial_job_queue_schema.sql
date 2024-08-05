CREATE TYPE JobState AS ENUM(
    'available',
    'completed',
    'failed',
    'running'
);

CREATE TYPE WaitingOn AS ENUM(
    'fetch',
    'hog'
);

CREATE TABLE IF NOT EXISTS cyclotron_jobs (
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    state JobState NOT NULL,
    waiting_on WaitingOn NOT NULL,
    queue_name TEXT NOT NULL,
    priority SMALLINT NOT NULL,
    function_id UUID,
    created TIMESTAMPTZ NOT NULL,
    last_transition TIMESTAMPTZ NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    transition_count SMALLINT NOT NULL,
    vm_state TEXT,
    metadata TEXT,
    parameters TEXT
);

-- For a given worker, the set of "available" jobs depends on state, waiting_on, queue_name,
-- and scheduled (so we can exclude sleeping jobs). This index is partial, because we don't care about
-- other states for the purpose of dequeuing
CREATE INDEX idx_queue_dequeue_partial ON cyclotron_jobs(state, waiting_on, queue_name, scheduled) WHERE state = 'available';
