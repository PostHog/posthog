-- Union-find pointer for person merges: a merged person stays in place and
-- points at its survivor instead of having its distinct id mappings moved.
-- NULL = live person, which is the correct value for every existing row, so
-- there is no backfill.
--
-- SAFE: ADD COLUMN with no default is metadata-only on PG 11+ — no table
-- rewrite, no scan, regardless of table size. The remaining hazard is the
-- brief ACCESS EXCLUSIVE lock; lock_timeout bounds the wait, and on timeout
-- the per-file transaction aborts and the next migration run retries this
-- idempotent file.

SET LOCAL lock_timeout = '2s';

ALTER TABLE posthog_person
    ADD COLUMN IF NOT EXISTS merged_into_id BIGINT;

-- The writer's validation target mirrors posthog_person, so it must carry
-- the column too.
ALTER TABLE personhog_person_tmp
    ADD COLUMN IF NOT EXISTS merged_into_id BIGINT;

-- Child lookup for union walks (emissions, maintenance, reaper). Partial:
-- only merged persons appear in it, so inserts of normal persons never
-- touch it.
--
-- On a large partitioned table this cascading build scans every partition
-- under a SHARE lock. Before this file reaches an environment where that
-- matters, build the per-partition indexes CONCURRENTLY out of band with
-- matching names, create the parent with ON ONLY, and ATTACH them; this
-- statement then no-ops via IF NOT EXISTS.
CREATE INDEX IF NOT EXISTS posthog_person_merged_into_idx
    ON posthog_person (merged_into_id)
    WHERE merged_into_id IS NOT NULL;
