CREATE TYPE JobState AS ENUM(
    'available',
    'completed',
    'failed',
    'running',
    'paused'
);


---------------------------------------------------------------------
-- Job table
---------------------------------------------------------------------
-- When a job is dequeued, it is locked by generating a UUID and returning it to the dequeuing
-- worker. Any worker that can't provide the correct lock_id when updating will have their updates
-- rejected. The reason this is important is because if, e.g., a worker holds a job in a running
-- state without updating the heartbeat, the janitor will return the job to the queue eventually,
-- and if the worker /then/ tries to update the job after another worker has picked it up, that's a
-- race. We track transition count and times alongside lock_id's and heartbeats for reporting and
-- debugging purposes, and we track the number of times the janitor has touched a job to spot poison
-- pills.
CREATE TABLE IF NOT EXISTS cyclotron_jobs (
    ---------------------------------------------------------------------
    -- Job metadata
    ---------------------------------------------------------------------
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    function_id UUID,
    created TIMESTAMPTZ NOT NULL,
    ---------------------------------------------------------------------
    -- Queue bookkeeping - invisible to the worker
    ---------------------------------------------------------------------
    lock_id UUID,
    -- This is set when a job is in a running state, and is required to update the job.
    last_heartbeat TIMESTAMPTZ,
    -- This is updated by the worker to indicate that the job is making forward progress even
    -- without transitions (and should not be reaped)
    janitor_touch_count SMALLINT NOT NULL,
    transition_count SMALLINT NOT NULL,
    last_transition TIMESTAMPTZ NOT NULL,
    ---------------------------------------------------------------------
    -- Queue components - determines which workers will consume this job
    ---------------------------------------------------------------------
    queue_name TEXT NOT NULL,
    ---------------------------------------------------------------------
    -- Job availability and priority (can this job be dequeued, and in what order?)
    ---------------------------------------------------------------------
    state JobState NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    priority SMALLINT NOT NULL,
    ---------------------------------------------------------------------
    -- Job data
    ---------------------------------------------------------------------
    vm_state TEXT,
    -- This is meant for workers "talking to themselves", e.g. tracking retries or something
    metadata TEXT,
    -- This is meant for "the next guy" - hog might fill it with a URL to fetch, for example
    parameters TEXT
);

-- For a given worker, the set of "available" jobs depends on state, queue_name, and scheduled (so
-- we can exclude sleeping jobs). This index is partial, because we don't care about other states
-- for the purpose of dequeuing
CREATE INDEX idx_cyclotron_jobs_dequeue ON cyclotron_jobs (queue_name, state, scheduled, priority)
WHERE
    state = 'available';

-- We create simple indexes on team_id, function_id and queue_name to support fast joins to future
-- control tables
CREATE INDEX idx_queue_team_id ON cyclotron_jobs(team_id);

CREATE INDEX idx_queue_function_id ON cyclotron_jobs(function_id);

CREATE INDEX idx_queue_queue_name ON cyclotron_jobs(queue_name);


---------------------------------------------------------------------
-- Control tables
---------------------------------------------------------------------

-- A simple key/value store, mostly used to let the janitor tell workers things like shard ID. This is
-- a backchannel we should be careful to use sparingly, it just saves us from duplicating constants
-- in N+1 config files.
CREATE TABLE IF NOT EXISTS cyclotron_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);


-- These are just a starting point, supporting overriding the state for a given team, function or queue
-- For now these are entirely unused
CREATE TABLE IF NOT EXISTS cyclotron_team_control (
    team_id INT PRIMARY KEY,
    state_override JobState,
    -- If this is not null, it overrides the state of all jobs for this team (allowing for e.g. pausing or force failing all of a teams jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);

CREATE TABLE IF NOT EXISTS cyclotron_function_control (
    function_id UUID PRIMARY KEY,
    state_override JobState,
    -- If this is not null, it overrides the state of all jobs for this function (allowing for e.g. pausing or force failing all of a functions jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);

CREATE TABLE IF NOT EXISTS cyclotron_queue_control (
    queue_name TEXT PRIMARY KEY,
    state_override JobState,
    -- If this is not null, it overrides the state of all jobs for this queue (allowing for e.g. pausing or force failing all of a queues jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);