-- The claim table is a churn table by design: the saga inserts one row per person per merge or
-- delete, walks that row through its statuses, and the GC pass a day later deletes the parent op
-- row, which cascades the claim rows away. A delete can never take the heap-only tuple path, so
-- every pass leaves dead entries in the primary key and in the partial mark index that the claim
-- insert's `ON CONFLICT` clause has to probe. The status transitions add to that while `status`
-- stays in the mark index predicate.
--
-- Default autovacuum waits for 20% dead tuples. That bloat is on the write path of every merge
-- and delete, because the claim insert is the saga's first step. 2% keeps the conflict probe on
-- live tuples.
--
-- Both the real table and its shadow twin are tuned. The validation table set takes the saga
-- writes today, and the real set takes them at cutover.
--
-- SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the sagas' reads and
-- writes. It does conflict with vacuum, analyze, and other maintenance DDL, so the statement can
-- wait behind an in-progress autovacuum on this table. lock_timeout bounds that wait: on timeout
-- the per-file transaction aborts, nothing is recorded, and the next migration run retries it.
--
-- This migration is idempotent and safe to re-run.

SET LOCAL lock_timeout = '5s';

ALTER TABLE lifecycle_op_person SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE lifecycle_op_person_tmp SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02
);
