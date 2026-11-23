-- no-transaction
--
-- Lets the email worker find due sends with files without scanning the plain sends ahead of them.
-- Its second poller dequeues only rows with file_bytes set, in the same order as the main poller:
--     ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
-- The partial predicate keeps the index as small as the number of waiting sends with files,
-- and matches idx_cyclotron_jobs_email_priority_fair_dequeue in its key columns.
--
-- Recovery note: an interrupted CONCURRENTLY build leaves the index INVALID, and a rerun's IF NOT EXISTS
-- does not rebuild it. sqlx runs a no-transaction file as one batch, so a drop cannot share this file. Recover by hand:
--   DROP INDEX CONCURRENTLY idx_cyclotron_jobs_email_files_fair_dequeue;  -- then rerun the migrations
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_files_fair_dequeue
    ON cyclotron_jobs (priority, dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'email' AND file_bytes IS NOT NULL;
