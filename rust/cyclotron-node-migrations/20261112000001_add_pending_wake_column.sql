-- Wait wakes the subscription matcher found while a worker held the job, keyed by wait step id.
-- Each entry holds a few short strings. The worker turns a fresh entry into a wake when it parks the job.
--
-- ADD COLUMN with no default only changes the catalog, but it still takes a brief ACCESS EXCLUSIVE lock
-- on a hot table. On a lock timeout the migration aborts, and the next run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS pending_wake JSONB;
