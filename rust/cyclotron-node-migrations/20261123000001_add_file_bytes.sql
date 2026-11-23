-- The total size of the attachment files an email job carries, or NULL for a job without files.
-- The email worker reads it to dequeue sends with files apart from plain sends, and only when it has memory for them.
-- It is a number, never the bytes: the files stay in object storage.
--
-- ADD COLUMN with no default is metadata-only, but it takes a brief ACCESS EXCLUSIVE lock that every dequeue
-- waits on. lock_timeout bounds that wait, and the next migration run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS file_bytes BIGINT;
