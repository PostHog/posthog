-- no-transaction
--
-- Drops the predecessor of idx_cyclotron_jobs_email_fair_dequeue_v2 (the
-- loose-predicate variant that included NULL-seq rows). The replacement
-- index was created in the previous migration; from this point on
-- fairDequeueJobs is served exclusively by the new tightened index.
DROP INDEX CONCURRENTLY IF EXISTS idx_cyclotron_jobs_email_fair_dequeue;
