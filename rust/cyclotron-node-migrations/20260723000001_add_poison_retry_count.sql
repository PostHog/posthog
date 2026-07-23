-- Poison-pill park-and-retry: when the janitor gives up on a poison pill it now
-- PARKS the job (scheduled far in the future so no worker dequeues it) instead of
-- deleting it, and the autodrain releases it back to its queue by moving scheduled
-- to now. poison_retry_count is NULL for normal jobs and set (>= 0) only on parked
-- poison pills; the autodrain increments it per release and stops at max_attempts,
-- so a perpetually-poison job is retried a bounded number of times then left parked.
ALTER TABLE cyclotron_jobs
    ADD COLUMN IF NOT EXISTS poison_retry_count SMALLINT;

-- Partial index for the autodrain's release scan: only parked poison rows carry a
-- non-NULL count, so this stays tiny regardless of overall table size.
CREATE INDEX IF NOT EXISTS idx_cyclotron_jobs_poison_retry
    ON cyclotron_jobs (poison_retry_count)
    WHERE poison_retry_count IS NOT NULL;
