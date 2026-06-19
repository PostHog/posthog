-- no-transaction
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_person_id
    ON cyclotron_jobs (team_id, person_id)
    WHERE person_id IS NOT NULL;
