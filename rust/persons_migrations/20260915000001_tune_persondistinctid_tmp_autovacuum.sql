-- `person_id` and `is_deleted` both sit under an index on this table, and both lifecycle write
-- paths rewrite them: the merge saga repoints `person_id` and bumps `version`, and the delete
-- saga tombstones `is_deleted` and bumps `version`. Neither update can take the heap-only tuple
-- path, so each one writes a new heap tuple plus entries in every index, and leaves the old
-- entries as dead tuples.
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
