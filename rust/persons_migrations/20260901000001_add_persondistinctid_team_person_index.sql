-- no-transaction
--
-- Distinct-id lookups filter posthog_persondistinctid on
-- (team_id, person_id, is_deleted = false), but the only index for that shape
-- is a bare person_id btree. So each lookup walks the person_id index and then
-- heap-checks team_id and is_deleted on every matched row. On the personhog
-- fetch this reads up to 2500 rows per person before the caller's small limit
-- applies, and the read grows with how many ids a person has rather than how
-- many the caller wants. This runs on the ingestion merge path at a high rate.
--
-- This partial composite index serves the filter directly and excludes the
-- tombstoned rows, so a lookup reads a short index range instead of scanning
-- the person_id index and re-checking the heap.
--
-- CONCURRENTLY, alone in its own no-transaction file: a plain CREATE INDEX takes
-- SHARE on posthog_persondistinctid, which conflicts with the ROW EXCLUSIVE that
-- every ingestion merge write needs, and the build would hold that lock until it
-- finishes. This table is on the hot ingestion write path, so a blocking build
-- stalls writes for the whole build.
--
-- Recovery note: if this build is interrupted it leaves the index INVALID, and a
-- rerun's IF NOT EXISTS does NOT rebuild it. Nothing reports that state, so check
-- it before assuming the index exists:
--   SELECT indisvalid FROM pg_index
--   WHERE indexrelid = to_regclass('posthog_persondistinctid_team_person_active');
-- On 'f', drop it and re-run migrations:
--   DROP INDEX CONCURRENTLY posthog_persondistinctid_team_person_active;
CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_persondistinctid_team_person_active
    ON posthog_persondistinctid (team_id, person_id)
    WHERE is_deleted = false;
