-- Reshape the handoff queue for the Postgres drain (posthog/dags/person_pg_cleanup_drain.py).
--
-- The drain pages the primary key by keyset and DELETEs each row once personhog has resolved
-- its person, so:
--
-- * cleaned_at was a completion marker for a drain that kept its rows. A drained row no longer
--   exists, so the column carries nothing.
-- * person_pg_cleanup_queue_drain, the partial index on (deleted_at), cannot page the queue:
--   every row of one sweep run carries the same deleted_at, so a keyset over it never advances.
--   The primary key is the drain's scan order.
-- * blocked_at records a row the drain could not resolve on its own: personhog reported the
--   person tombstoned but still owning a live distinct id, or owning more distinct ids than one
--   delete transaction may touch, or the delete request kept failing. The drain skips such rows
--   until a retry interval passes, and operators find them with WHERE blocked_at IS NOT NULL. The
--   sweep clears it when it queues the same person again.
--
-- SAFE: metadata-only ALTERs and an index drop on a small table that only the sweep and the
-- drain touch. Each statement takes a brief ACCESS EXCLUSIVE lock; no table rewrite. Idempotent.

SET LOCAL lock_timeout = '5s';

DROP INDEX IF EXISTS person_pg_cleanup_queue_drain;

ALTER TABLE person_pg_cleanup_queue DROP COLUMN IF EXISTS cleaned_at;

ALTER TABLE person_pg_cleanup_queue ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMP WITH TIME ZONE;

COMMENT ON TABLE person_pg_cleanup_queue IS
    'Persons the ClickHouse sweep removed, awaiting a Postgres hard delete by person_pg_cleanup_drain_job. Rows are deleted once drained.';
COMMENT ON COLUMN person_pg_cleanup_queue.deleted_at IS
    'When the ClickHouse sweep finished removing the person; one value per sweep run.';
COMMENT ON COLUMN person_pg_cleanup_queue.blocked_at IS
    'Set when the drain could not resolve the person: a live distinct id remains, the person owns too many distinct ids, or the delete request kept failing. Cleared when the sweep queues the person again.';
