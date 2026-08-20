-- no-transaction
--
-- Adds a priority-first variant of the email fair-dequeue index, so the email
-- worker can serve transactional-class sends ahead of bulk/marketing-class
-- sends while keeping the per-team interleave within each class.
--
-- The email worker's priority dequeue orders by
--     ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
-- Leading on `priority` lets that ORDER BY be satisfied by index order, and
-- `scheduled` as a trailing key column keeps `scheduled <= NOW()` as an
-- `Index Cond` rather than a heap-level filter, matching the rationale for
-- idx_cyclotron_jobs_email_fair_dequeue_v2 (which stays in place until the
-- new ordering is enabled everywhere and is dropped in a follow-up).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_priority_fair_dequeue
    ON cyclotron_jobs (priority, dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'email';
