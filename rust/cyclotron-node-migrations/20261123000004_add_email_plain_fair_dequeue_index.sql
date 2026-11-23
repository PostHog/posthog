-- no-transaction
--
-- Lets the email worker's main poller claim plain sends in fair order without reading the sends with files ahead of them.
-- When more due plain sends wait than the bounded due scan takes, the poll falls back to
--     ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
-- with file_bytes IS NULL. idx_cyclotron_jobs_email_priority_fair_dequeue does not hold file_bytes, so without this
-- index that fallback reads every send with files ahead in fair order from the heap and discards it.
-- idx_cyclotron_jobs_email_plain_due keeps serving the due scan, which orders by scheduled instead.
--
-- Recovery note: an interrupted CONCURRENTLY build leaves the index INVALID, and a rerun's IF NOT EXISTS
-- does not rebuild it. sqlx runs a no-transaction file as one batch, so a drop cannot share this file. Recover by hand:
--   DROP INDEX CONCURRENTLY idx_cyclotron_jobs_email_plain_fair_dequeue;  -- then rerun the migrations
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_plain_fair_dequeue
    ON cyclotron_jobs (priority, dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'email' AND file_bytes IS NULL;
