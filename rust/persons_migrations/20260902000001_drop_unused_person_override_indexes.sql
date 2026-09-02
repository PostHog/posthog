-- Drop the unused indexes on posthog_personoverride.
--
-- The table has had no reader or writer since the plugin-server override writer
-- was removed (see https://github.com/PostHog/posthog/pull/23616). pganalyze flags
-- the three btrees and the index behind the exclusion constraint as unused on every
-- persons cluster. Drop them.
--
-- The unique index unique_override_per_old_person_id stays: it backs a uniqueness
-- rule rather than a lookup, so pganalyze does not count it as unused.
--
-- The lock and retry reasoning is the same as
-- 20260901000001_drop_unused_flat_person_override_index.sql: the runner wraps each
-- file in a transaction, lock_timeout bounds the ACCESS EXCLUSIVE wait, and IF EXISTS
-- keeps the retry a no-op.
--
-- The copies of these tables in the main database keep their indexes. That database
-- is not reachable from here, and pganalyze reports only the persons clusters.

SET LOCAL lock_timeout = '2s';

ALTER TABLE posthog_personoverride
    DROP CONSTRAINT IF EXISTS exclude_override_person_id_from_being_old_person_id;

DROP INDEX IF EXISTS posthog_personoverride_old_person_id_4c1deac0;
DROP INDEX IF EXISTS posthog_personoverride_override_person_id_9f32aab1;
DROP INDEX IF EXISTS posthog_personoverride_team_id_92291e67;
