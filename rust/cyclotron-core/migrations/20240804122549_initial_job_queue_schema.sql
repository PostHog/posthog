CREATE TYPE JobState AS ENUM(
    'available',
    'completed',
    'failed',
    'running',
    'paused'
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

-- The locking behaviour deserves some explanation. When a job is dequeued, it is locked by generating a UUID
-- and returning it to the dequeuing worker. Any worker that can't provide the correct lock_id when updating
-- will have their updates rejected. The reason this is important is because if, e.g., a worker holds a job
-- in a running state without updating the heartbeat, the janitor will return the job to the queue eventually,
-- and if the worker /then/ tries to update the job after another worker has picked it up, that's a race. We
-- track transition count and times alongside lock_id's and heartbeats for reporting and debugging purposes,
-- and we track the number of times the janitor has touched a job to spot poison pills.

CREATE TABLE IF NOT EXISTS cyclotron_jobs (
-- Job metadata - fixed
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    function_id UUID,
    created TIMESTAMPTZ NOT NULL,
-- Queue bookkeeping - invisible to the worker
    lock_id UUID, -- This is set when a job is in a running state, and is required to update the job.
    last_heartbeat TIMESTAMPTZ, -- This is updated by the worker to indicate that the job is making forward progress even without transitions (and should not be reaped)
    janitor_touch_count SMALLINT NOT NULL,
    transition_count SMALLINT NOT NULL,
    last_transition TIMESTAMPTZ NOT NULL,
-- "Virtual queue" components - roughly what determines which workers will consume this job
    queue_name TEXT NOT NULL,
    waiting_on WaitingOn NOT NULL,
-- Job availability and priority (can this job be dequeued, and in what order?)
    state JobState NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    priority SMALLINT NOT NULL,
-- Job data
    vm_state TEXT,
    metadata TEXT, -- This is meant for workers "talking to themselves", e.g. tracking retries or something
    parameters TEXT -- This is meant for "the next guy" - hog might fill it with a URL to fetch, for example
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
