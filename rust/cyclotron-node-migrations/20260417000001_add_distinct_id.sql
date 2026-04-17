-- Add distinct_id as a top-level column so the subscription matcher consumer
-- can efficiently find parked hogflow jobs by person without parsing state.
ALTER TABLE cyclotron_jobs ADD COLUMN distinct_id TEXT;

CREATE INDEX idx_cyclotron_jobs_distinct_id
    ON cyclotron_jobs (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;
