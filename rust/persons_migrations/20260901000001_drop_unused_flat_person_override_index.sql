-- Drop the unused index on posthog_flatpersonoverride.
--
-- The table has had no reader or writer since the plugin-server override writer
-- was removed (see https://github.com/PostHog/posthog/pull/23616). pganalyze flags
-- posthog_fla_team_id_224253_idx as unused on every persons cluster. Drop it.
--
-- SAFE: the migration runner wraps each file in a transaction, so DROP INDEX runs
-- without CONCURRENTLY. A plain drop takes a brief lock, but the table carries no
-- live reads or writes, so nothing waits behind it. IF EXISTS keeps it idempotent.

DROP INDEX IF EXISTS posthog_fla_team_id_224253_idx;
