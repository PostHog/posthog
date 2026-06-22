-- no-transaction
--
-- Adds `INCLUDE (scheduled)` to the email fair-dequeue index so the worker's
-- `scheduled <= NOW()` filter can be evaluated from the index entry instead
-- of requiring a heap visit for every walked-past row.
--
-- Why: under fair dequeue, the planner walks the index in `dequeue_seq` order
-- to satisfy `ORDER BY dequeue_seq ASC NULLS FIRST`. Future-scheduled rows sit
-- in the partial index alongside ready rows, and without `scheduled` in the
-- index each one forces a heap visit just to be filtered out. That's the
-- walk-past cost: it scales linearly with the size of the future-scheduled
-- backlog for a single tenant or across tenants.
--
-- With `INCLUDE (scheduled)`, the planner can satisfy the filter from the
-- index entry. Heap visits only happen for rows we're actually returning, so
-- a 1M-row future-scheduled batch no longer turns into 1M heap visits per
-- poll.
--
-- Predicate is unchanged from the original index, and the sort key still
-- matches the worker's `ORDER BY dequeue_seq ASC NULLS FIRST`.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue_v2
    ON cyclotron_jobs (dequeue_seq NULLS FIRST)
    INCLUDE (scheduled)
    WHERE status = 'available' AND queue_name = 'email';
