-- The sweep index puts `version` under an index, and the membership consumer rewrites `version` on
-- every message, so those upserts can no longer take the heap-only tuple path: each one writes a
-- new heap tuple plus an entry in all four indexes, and leaves the old entries as dead tuples.
-- Before the index, the upsert only changed `in_cohort` and `last_updated`, neither of them
-- indexed, so it reused the heap page and touched no index at all.
--
-- Default autovacuum waits for 20% dead tuples, which is a large amount of bloat on a table the
-- flag evaluation path reads under a 1000ms timeout. 2% keeps the index scans on live tuples.
--
-- SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the consumer's writes.

ALTER TABLE cohort_membership SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02
);
