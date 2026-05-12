-- no-transaction
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_distinct_id
    ON cyclotron_jobs (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;
