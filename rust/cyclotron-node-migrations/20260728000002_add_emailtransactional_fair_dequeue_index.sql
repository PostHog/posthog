-- no-transaction
--
-- Fair-dequeue index for the emailtransactional queue, mirroring
-- idx_cyclotron_jobs_email_fair_dequeue_v2. See
-- 20260622000001_add_email_fair_dequeue_composite_index.sql for why
-- `scheduled` is a key column rather than INCLUDE'd: as a non-leading key it
-- becomes an Index Cond evaluated during the index walk instead of a
-- heap-level Filter, and the leading `dequeue_seq NULLS FIRST` satisfies the
-- worker's ORDER BY without a Sort node.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_emailtransactional_fair_dequeue
    ON cyclotron_jobs (dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'emailtransactional';
