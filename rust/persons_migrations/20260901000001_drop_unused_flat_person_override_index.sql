-- Drop the unused index on posthog_flatpersonoverride.
--
-- The table has had no reader or writer since the plugin-server override writer
-- was removed (see https://github.com/PostHog/posthog/pull/23616). pganalyze flags
-- posthog_fla_team_id_224253_idx as unused on every persons cluster. Drop it.
--
-- SAFE: the migration runner wraps each file in a transaction, so DROP INDEX runs
-- without CONCURRENTLY. A plain drop takes a brief ACCESS EXCLUSIVE lock. The table
-- carries no live reads or writes, so nothing queues behind the drop, but the drop
-- can still queue behind an outside session (a logical dump, a manual psql).
-- lock_timeout bounds that wait; on timeout the per-file transaction aborts, nothing
-- is recorded, and the next migration run retries this idempotent file. IF EXISTS
-- keeps the retry a no-op once the index is gone.

SET LOCAL lock_timeout = '2s';

DROP INDEX IF EXISTS posthog_fla_team_id_224253_idx;
