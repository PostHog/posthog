-- no-transaction
--
-- Lets the email worker's files poller find due sends with files without reading the ones scheduled later.
-- Its due scan walks each priority class in scheduled order and stops at the first row not yet due:
--     WHERE priority = $p AND scheduled <= NOW() ORDER BY scheduled ASC
-- idx_cyclotron_jobs_email_files_fair_dequeue leads with dequeue_seq, so without this index each poll walks
-- every waiting send with files, future ones included, to find the due ones.
--
-- An interrupted build leaves the index INVALID, and the rerun's IF NOT EXISTS skips it.
-- Rebuild it with REINDEX INDEX CONCURRENTLY.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_files_due
    ON cyclotron_jobs (priority, scheduled)
    WHERE status = 'available' AND queue_name = 'email' AND file_bytes IS NOT NULL;
