-- no-transaction
--
-- Lets the email worker find due sends with files without scanning the plain sends ahead of them.
-- Its second poller dequeues only rows with file_bytes set, in the same order as the main poller:
--     ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
-- The partial predicate keeps the index as small as the number of waiting sends with files,
-- and matches idx_cyclotron_jobs_email_priority_fair_dequeue in its key columns.
--
-- An interrupted build leaves the index INVALID, and the rerun's IF NOT EXISTS skips it.
-- rust/bin/migrate-entry rebuilds it after the migrations run.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_files_fair_dequeue
    ON cyclotron_jobs (priority, dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'email' AND file_bytes IS NOT NULL;
