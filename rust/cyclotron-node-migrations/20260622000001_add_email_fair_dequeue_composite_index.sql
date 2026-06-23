-- no-transaction
--
-- Replaces the email fair-dequeue index with a composite-key variant that
-- adds `scheduled` as a secondary key column. This lets the planner apply
-- `scheduled <= NOW()` as an `Index Cond` evaluated during the index walk,
-- instead of a heap-level `Filter:` that fetches every walked-past row.
--
-- Why not `INCLUDE (scheduled)`? Empirically (EXPLAIN ANALYZE BUFFERS at
-- 1M future-scheduled rows + 100K dequeueable), `INCLUDE` does NOT cause
-- Postgres to skip heap fetches for filtered rows under this query shape.
-- The filter is still evaluated after the heap visit, so the buffer count
-- and execution time match the un-INCLUDE'd index. A composite key with
-- `scheduled` as a non-leading key column flips the planner to `Index Cond`
-- — walked-past rows are eliminated in-index, dropping buffer reads ~4x
-- and execution time ~10x at the same scale.
--
-- The leading key is still `dequeue_seq NULLS FIRST`, so the worker's
-- `ORDER BY dequeue_seq ASC NULLS FIRST` is satisfied by the index sort
-- order without a separate Sort node.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue_v2
    ON cyclotron_jobs (dequeue_seq NULLS FIRST, scheduled)
    WHERE status = 'available' AND queue_name = 'email';
