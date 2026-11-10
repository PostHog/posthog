-- One row per caller-supplied idempotency key, written in the same transaction as the job it
-- queued. It is not a cyclotron_jobs row because the janitor deletes a job seconds after it
-- finishes, and a repeat must stay deduplicated for the whole retry window.
CREATE TABLE IF NOT EXISTS cyclotron_idempotency_keys (
    -- The invocation id, which the caller derives from the team and the key, so a retry carries
    -- the same id.
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    -- sha256 of the request, so a key reused for a different request is told apart from a retry.
    fingerprint TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Drives the janitor's expiry sweep.
CREATE INDEX IF NOT EXISTS idx_cyclotron_idempotency_keys_expires_at
    ON cyclotron_idempotency_keys (expires_at);
