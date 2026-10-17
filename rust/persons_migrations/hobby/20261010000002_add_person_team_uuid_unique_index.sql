-- no-transaction
--
-- Hobby only. Person merges upsert with ON CONFLICT (team_id, uuid), and Postgres needs a unique
-- index on those columns to resolve that target. Production gets one from the partitioned
-- person table migration, which hobby skips.
--
-- Recovery note: if this CONCURRENTLY build is ever interrupted, it leaves the index
-- INVALID and a rerun's IF NOT EXISTS will NOT rebuild it. Recover manually:
--   DROP INDEX CONCURRENTLY posthog_person_team_id_uuid_uniq;
-- then re-run migrations.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS posthog_person_team_id_uuid_uniq
    ON posthog_person (team_id, uuid);
