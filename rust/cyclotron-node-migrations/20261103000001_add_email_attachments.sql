-- The files of a transactional email, one row per file, written by the API before it queues the job.
--
-- The bytes stay out of cyclotron_jobs.state on purpose: the state is rewritten on every retry and
-- copied into the lifecycle snapshot in Kafka and ClickHouse, and the snapshot must never carry a
-- customer's file. The job state keeps only each file's name, type, size and SHA-256, and the email
-- worker checks the rows against them before it sends.
--
-- The worker deletes the rows when the send reaches a terminal outcome. The janitor deletes the rows
-- of a job that never got there, by created_at.
CREATE TABLE IF NOT EXISTS cyclotron_email_attachments (
    id UUID PRIMARY KEY,
    -- The cyclotron_jobs.id of the email job. Not a foreign key, because the janitor deletes finished
    -- jobs on its own schedule and the rows must outlive a job only until the sweep.
    job_id UUID NOT NULL,
    team_id BIGINT NOT NULL,
    -- The file's index in the request, so the email keeps the order the caller sent.
    position SMALLINT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    content_id TEXT,
    content BYTEA NOT NULL,
    size_bytes INT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cyclotron_email_attachments_job_id
    ON cyclotron_email_attachments (job_id);

-- Drives the sweep of rows whose job never reached a terminal outcome.
CREATE INDEX IF NOT EXISTS idx_cyclotron_email_attachments_created_at
    ON cyclotron_email_attachments (created_at);
