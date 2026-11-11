CREATE TABLE IF NOT EXISTS cyclotron_email_attachments (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL,
    team_id BIGINT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_cyclotron_email_attachments_created_at
    ON cyclotron_email_attachments (created_at);
