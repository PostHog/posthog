ALTER TABLE cyclotron_jobs ADD COLUMN distinct_id TEXT;
ALTER TABLE cyclotron_jobs ADD COLUMN action_id TEXT;

CREATE INDEX idx_cyclotron_jobs_distinct_id
    ON cyclotron_jobs (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;
