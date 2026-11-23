-- The total size of the attachment files an email job carries, or NULL for a job without files.
-- The email worker reads it to dequeue sends with files apart from plain sends, and only when it has memory for them.
-- It is a number, never the bytes: the files stay in object storage.
--
-- ADD COLUMN with no default changes only the catalog, but it needs an ACCESS EXCLUSIVE lock on cyclotron_jobs.
-- While the ALTER waits for that lock behind a long transaction, new dequeues queue behind the ALTER.
-- lock_timeout ends the ALTER's own wait, which also releases the dequeues queued behind it, and the next
-- migration run retries this idempotent file. Once granted, the lock is held until this migration's
-- transaction commits, right after the catalog change.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS file_bytes BIGINT;
