-- What the first request was answered, so a retry gets the same answer after its job is deleted.
ALTER TABLE cyclotron_idempotency_keys ADD COLUMN IF NOT EXISTS reply JSONB;
