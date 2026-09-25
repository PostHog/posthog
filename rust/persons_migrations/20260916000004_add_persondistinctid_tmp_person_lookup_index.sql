-- no-transaction
--
-- Shadow-table counterpart of posthog_persondistinctid_person_lookup_idx. The
-- identity service reads whichever distinct id table its config names, so the
-- validation set needs the same plan as the real pair.
--
-- Recovery note: if this CONCURRENTLY build is ever interrupted, it leaves the index
-- INVALID and a rerun's IF NOT EXISTS will NOT rebuild it. Recover manually:
--   DROP INDEX CONCURRENTLY personhog_persondistinctid_tmp_person_lookup_idx;
-- then re-run migrations.
CREATE INDEX CONCURRENTLY IF NOT EXISTS personhog_persondistinctid_tmp_person_lookup_idx
    ON personhog_persondistinctid_tmp (person_id, team_id, is_deleted, id)
    INCLUDE (distinct_id, version);
