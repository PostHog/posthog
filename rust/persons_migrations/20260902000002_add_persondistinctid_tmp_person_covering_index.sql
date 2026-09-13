-- no-transaction
--
-- The same covering index on the validation shadow table. 20260902000001
-- carries the rationale; this file exists because CONCURRENTLY statements must
-- be alone in a no-transaction file.
--
-- Recovery note: an interrupted CONCURRENTLY build leaves the index INVALID
-- and a rerun's IF NOT EXISTS will NOT rebuild it. Check before assuming the
-- index is there:
--   SELECT indisvalid FROM pg_index
--    WHERE indexrelid = to_regclass('personhog_persondistinctid_tmp_person_live_covering_idx');
-- On `f`, drop it first:
--   DROP INDEX CONCURRENTLY personhog_persondistinctid_tmp_person_live_covering_idx;
-- Then re-run migrations if this file is not yet recorded as applied, or run
-- the statement below by hand if it is. 20260901000003 explains why.
CREATE INDEX CONCURRENTLY IF NOT EXISTS personhog_persondistinctid_tmp_person_live_covering_idx
    ON personhog_persondistinctid_tmp (person_id, team_id, id) INCLUDE (distinct_id, version)
    WHERE is_deleted = false;
