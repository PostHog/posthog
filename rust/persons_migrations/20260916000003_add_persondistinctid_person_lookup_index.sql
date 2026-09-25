-- no-transaction
--
-- Covering index for the person -> distinct id expansion that personhog-replica and
-- personhog-identity both run. It filters on team_id, person_id and is_deleted, and
-- returns distinct_id, version and id. Only person_id was indexed, so team_id and
-- is_deleted were heap filters and every candidate row cost a random heap read; with
-- the three predicates as key columns and the returned columns along for the ride,
-- the lookup becomes an index-only scan.
--
-- person_id leads so this index is a superset of
-- posthog_persondistinctid_person_id_5d655bba, which a later migration can drop once
-- the plans have settled.
--
-- Recovery note: if this CONCURRENTLY build is ever interrupted, it leaves the index
-- INVALID and a rerun's IF NOT EXISTS will NOT rebuild it. Recover manually:
--   DROP INDEX CONCURRENTLY posthog_persondistinctid_person_lookup_idx;
-- then re-run migrations.
CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_persondistinctid_person_lookup_idx
    ON posthog_persondistinctid (person_id, team_id, is_deleted, id)
    INCLUDE (distinct_id, version);
