-- No code writes posthog_group.properties_last_updated_at or properties_last_operation.
-- Both columns are NOT NULL with no default in prod, because the table predates the
-- CREATE TABLE IF NOT EXISTS in 20250923000001, so an insert that omits them fails.
--
-- SAFE: SET DEFAULT changes only the catalog and rewrites no rows. lock_timeout bounds the
-- brief ACCESS EXCLUSIVE wait, so the migration fails fast instead of queueing group writes
-- behind it. Idempotent.

SET LOCAL lock_timeout = '2s';

ALTER TABLE posthog_group
    ALTER COLUMN properties_last_updated_at SET DEFAULT '{}'::jsonb,
    ALTER COLUMN properties_last_operation SET DEFAULT '{}'::jsonb;
