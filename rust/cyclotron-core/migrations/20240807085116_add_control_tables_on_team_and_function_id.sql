-- Add migration script here


-- These are just a starting point, supporting overriding the state for a given team, function or queue
CREATE TABLE IF NOT EXISTS cyclotron_team_control (
    team_id INT PRIMARY KEY,
    state_override JobState, -- If this is not null, it overrides the state of all jobs for this team (allowing for e.g. pausing or force failing all of a teams jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);

CREATE TABLE IF NOT EXISTS cyclotron_function_control (
    function_id UUID PRIMARY KEY,
    state_override JobState, -- If this is not null, it overrides the state of all jobs for this function (allowing for e.g. pausing or force failing all of a functions jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);

CREATE TABLE IF NOT EXISTS cyclotron_queue_control (
    queue_name TEXT PRIMARY KEY,
    state_override JobState, -- If this is not null, it overrides the state of all jobs for this queue (allowing for e.g. pausing or force failing all of a queues jobs)
    state_override_expires TIMESTAMPTZ -- State override can be temporary or permanent
);