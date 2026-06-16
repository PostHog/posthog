-- no-transaction
--
-- Partial index supporting the email worker's fair dequeue ORDER BY.
-- Tight predicate: only covers email rows that are actually dequeueable.
-- Hog, hogflow, and any future queues never touch this index — their
-- dequeue continues to use idx_cyclotron_jobs_dequeue as before.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue
    ON cyclotron_jobs (dequeue_seq)
    WHERE status = 'available' AND queue_name = 'email';
