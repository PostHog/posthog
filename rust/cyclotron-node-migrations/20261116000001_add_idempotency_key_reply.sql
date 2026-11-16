-- What the first request was answered: a few small fields, so a retry gets the same answer after its job is deleted.
--
-- ADD COLUMN with no default is metadata-only, but it takes a brief ACCESS EXCLUSIVE lock that every keyed send
-- waits on. lock_timeout bounds that wait, and the next migration run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_idempotency_keys ADD COLUMN IF NOT EXISTS reply JSONB;
