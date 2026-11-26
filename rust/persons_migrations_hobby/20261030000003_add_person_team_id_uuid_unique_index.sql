-- no-transaction
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS posthog_person_team_id_uuid_uniq ON posthog_person (team_id, uuid);
