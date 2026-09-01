-- no-transaction
-- The matcher looks up parked waits with no person anchor on every distinct_id first mapping, which is a
-- high-volume stream. Only a handful of jobs lack an anchor at any moment, so a partial index keeps that
-- lookup to a few rows instead of leaning on the full (team_id, distinct_id) index.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_null_person_anchor
    ON cyclotron_jobs (team_id, distinct_id)
    WHERE person_id IS NULL AND distinct_id IS NOT NULL;
