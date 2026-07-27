-- no-transaction
--
-- Drops the original email fair-dequeue index, now superseded by the v2

-- variant with `scheduled` as a composite key column. The v2 index is created in the prior

-- migration, so the planner has a usable index throughout the deploy.
DROP INDEX CONCURRENTLY IF EXISTS idx_cyclotron_jobs_email_fair_dequeue;
