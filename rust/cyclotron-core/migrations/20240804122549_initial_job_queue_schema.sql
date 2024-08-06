CREATE TYPE JobState AS ENUM(
    'available',
    'completed',
    'failed',
    'running'
);

-- TODO - I go back and forth on whether this should just be an open text field,
-- rather than an enum - that makes it faster to add new kinds of workers to the
-- system (since you don't have to bump library versions for anything consuming the
-- cyclotron-core crate), but having a defined set of workers means you can spin up
-- a new one and know nobody (or almost nobody) will be pushing to it until you ship
-- a new version of the core crate.
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

-- We use priorty and scheduled to determine the order in which jobs are dequeued, so we need an index on those
-- TODO - I *think* this can be a partial index, but really I need to create a test dataset and run some explains
CREATE INDEX idx_queue_dequeue_priority_scheduled ON cyclotron_jobs(priority, scheduled) WHERE state = 'available';

-- We create simple indexes on team_id, function_id and queue_name to support fast joins to future control tables
CREATE INDEX idx_queue_team_id ON cyclotron_jobs(team_id);
CREATE INDEX idx_queue_function_id ON cyclotron_jobs(function_id);
CREATE INDEX idx_queue_queue_name ON cyclotron_jobs(queue_name);
