-- Wakes the subscription matcher could not deliver because the job was running. Keyed by
-- wait_until_condition action id; each entry is a few short strings, never a payload.
-- The worker's release write turns a fresh entry for the step it parks on into an immediate wake.
--
-- ADD COLUMN with no default is metadata-only, but still takes a brief ACCESS EXCLUSIVE lock on
-- a hot table. lock_timeout bounds the wait; on timeout the migration aborts and the next run
-- retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS pending_wake JSONB;
