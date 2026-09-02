-- Soft-delete tombstones for persons and distinct id mappings.
--
-- Person deletion (and merge source destruction) tombstones rows instead of
-- deleting them: is_deleted = true, version bumped past the sealed version,
-- properties cleared. Keeping the row means the Postgres tombstone carries the
-- same version as the ClickHouse tombstone, and re-creation of a previously
-- deleted key becomes a revival upsert (version bumped above the tombstone)
-- instead of an insert restarting at version 0 that loses to the ClickHouse
-- tombstone forever.
--
-- The unique index on (team_id, distinct_id) intentionally stays total
-- (tombstoned rows included) so a re-created distinct id conflicts with its
-- tombstone and takes the revival path.
--
-- SAFE: ADD COLUMN with a constant default is metadata-only on PG 11+
-- (stored as attmissingval; existing rows synthesize the value at read time)
-- — no table rewrite, no backfill, no NOT NULL validation scan, regardless of
-- table size. The remaining hazard is the brief ACCESS EXCLUSIVE lock: on a
-- hot table the danger is queueing for it behind a long-running query while
-- everything else queues behind us. lock_timeout bounds that wait; on timeout
-- the per-file transaction aborts, nothing is recorded, and the next
-- migration run retries this idempotent file.

SET LOCAL lock_timeout = '2s';

ALTER TABLE posthog_person
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE posthog_persondistinctid
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;

-- The writer's validation target mirrors posthog_person (minus is_user_id),
-- and the leader's PG fallback reads whichever of the two is configured, so
-- both must carry the column.
ALTER TABLE personhog_person_tmp
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;
