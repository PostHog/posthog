-- no-transaction
--
-- Partial index supporting the email worker's fair dequeue ORDER BY.
-- Tight predicate: only covers email rows that are actually dequeueable.
-- Hog, hogflow, and any future queues never touch this index — their
-- dequeue continues to use idx_cyclotron_jobs_dequeue as before.
--
-- `NULLS FIRST` matches the worker's `ORDER BY dequeue_seq ASC NULLS FIRST`
-- in `fairDequeueJobs`. Without aligning the index sort to the query, the
-- planner can't use the index to satisfy the ORDER BY and falls back to a
-- full sort of the available set on every dequeue.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue
    ON cyclotron_jobs (dequeue_seq NULLS FIRST)
    WHERE status = 'available' AND queue_name = 'email';
