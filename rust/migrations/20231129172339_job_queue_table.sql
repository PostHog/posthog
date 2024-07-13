CREATE TYPE job_status AS ENUM(
    'available',
    'completed',
    'failed',
    'running'
);

CREATE TABLE job_queue(
    id BIGSERIAL PRIMARY KEY,
    attempt INT NOT NULL DEFAULT 0,
    attempted_at TIMESTAMPTZ DEFAULT NULL,
    attempted_by TEXT [] DEFAULT ARRAY [] :: TEXT [],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    errors JSONB [],
    max_attempts INT NOT NULL DEFAULT 1,
    metadata JSONB,
    last_attempt_finished_at TIMESTAMPTZ DEFAULT NULL,
    parameters JSONB,
    queue TEXT NOT NULL DEFAULT 'default' :: text,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status job_status NOT NULL DEFAULT 'available' :: job_status,
    target TEXT NOT NULL
);

-- Needed for `dequeue` queries
CREATE INDEX idx_queue_scheduled_at ON job_queue(queue, status, scheduled_at, attempt);

-- Needed for UPDATE-ing incomplete jobs with a specific target (i.e. slow destinations)
CREATE INDEX idx_queue_target ON job_queue(queue, status, target);
