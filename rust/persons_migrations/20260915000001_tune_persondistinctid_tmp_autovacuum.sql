-- The merge saga repoints `person_id`, which carries its own index, so that update cannot take the
-- heap-only tuple path: each repoint writes a new heap tuple plus an entry in all three indexes,
-- and leaves the old entries as dead tuples. The delete saga writes `is_deleted` and `version`,
-- neither of them indexed, so it can reuse the heap page when that page has free space, but it
-- still leaves a dead heap tuple behind.
--
-- Default autovacuum waits for 20% dead tuples. On the shadow mapping table that is wasted
-- storage and slower index scans over the validation set we read to decide whether personhog is
-- correct. 2% keeps the scans on live tuples.
--
-- SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the sagas' writes.
--
-- This migration is idempotent and safe to re-run.

ALTER TABLE personhog_persondistinctid_tmp SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02
);
