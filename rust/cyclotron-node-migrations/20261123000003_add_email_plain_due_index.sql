-- no-transaction
--
-- Lets the email worker's main poller find due plain sends without reading the sends with files ahead of them.
-- Once sends with files have their own poller, the main poller's due scan skips them with
--     file_bytes IS NULL
-- idx_cyclotron_jobs_dequeue does not hold file_bytes, so without this index each poll reads every due send
-- with files from the heap and discards it, and a backlog of them slows every poll.
--
-- Recovery note: an interrupted CONCURRENTLY build leaves the index INVALID, and a rerun's IF NOT EXISTS
-- does not rebuild it. sqlx runs a no-transaction file as one batch, so a drop cannot share this file. Recover by hand:
--   DROP INDEX CONCURRENTLY idx_cyclotron_jobs_email_plain_due;  -- then rerun the migrations
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_plain_due
    ON cyclotron_jobs (priority, scheduled)
    WHERE status = 'available' AND queue_name = 'email' AND file_bytes IS NULL;
