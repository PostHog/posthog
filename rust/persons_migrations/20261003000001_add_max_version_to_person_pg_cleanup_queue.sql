-- The highest ClickHouse person version the sweep removed; the drain deletes the Postgres person only at or below it.
--
-- SAFE: nullable column with no default, so catalog-only; lock_timeout bounds the ACCESS EXCLUSIVE wait. Idempotent.

SET LOCAL lock_timeout = '2s';

ALTER TABLE person_pg_cleanup_queue ADD COLUMN IF NOT EXISTS max_version BIGINT;

COMMENT ON COLUMN person_pg_cleanup_queue.max_version IS
    'Highest ClickHouse person version the sweep removed. The drain deletes the Postgres person only at or below this version. NULL when no sweep recorded a bound; the drain leaves those rows in place.';
