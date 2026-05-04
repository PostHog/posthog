-- Top-level columns for looking up parked jobs by person and identifying
-- which workflow step is parked, without parsing the state blob. Partial
-- index keeps overhead negligible: distinct_id is NULL for jobs without
-- an associated person (most of them).
ALTER TABLE cyclotron_jobs ADD COLUMN distinct_id TEXT;
ALTER TABLE cyclotron_jobs ADD COLUMN action_id TEXT;

CREATE INDEX idx_cyclotron_jobs_distinct_id
    ON cyclotron_jobs (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;
