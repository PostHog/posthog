-- no-transaction
--
-- Shadow-table counterpart of lifecycle_op_person_mark_active.
--
-- Recovery note: if this CONCURRENTLY build is ever interrupted, it leaves the index
-- INVALID and a rerun's IF NOT EXISTS will NOT rebuild it. Recover manually:
--   DROP INDEX CONCURRENTLY lifecycle_op_person_tmp_mark_active;
-- then re-run migrations.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS lifecycle_op_person_tmp_mark_active
    ON lifecycle_op_person_tmp (team_id, person_id)
    WHERE mark_active = true;
