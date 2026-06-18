-- no-transaction
--
-- Tighten the partial-index predicate to exclude rows that don't have a
-- fair-dequeue seq assigned yet. Future-scheduled rows (whose seq is
-- assigned lazily by the janitor's promoteScheduledEmailJobs pass and the
-- email consumer's fallback interval) and any legacy NULL rows stay out
-- of the index, so the dequeue scan doesn't have to walk past them.
--
-- Dropping NULLS FIRST from the ordering — the new predicate guarantees
-- the index can't contain NULLs, and the query in worker.ts fairDequeueJobs
-- is updated in lockstep to drop the NULLS FIRST hint.
DROP INDEX CONCURRENTLY IF EXISTS idx_cyclotron_jobs_email_fair_dequeue;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue
    ON cyclotron_jobs (dequeue_seq ASC)
    WHERE status = 'available'
      AND queue_name = 'email'
      AND dequeue_seq IS NOT NULL;
