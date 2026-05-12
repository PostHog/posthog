ALTER TABLE cyclotron_jobs
    ADD COLUMN IF NOT EXISTS distinct_id TEXT,
    ADD COLUMN IF NOT EXISTS person_id UUID,
    ADD COLUMN IF NOT EXISTS action_id TEXT;
