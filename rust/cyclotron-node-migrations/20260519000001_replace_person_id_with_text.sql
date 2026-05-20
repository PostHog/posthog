-- The wait-until-event feature is not yet live, so we drop existing data and
-- re-create the column as TEXT so non-UUID person identifiers (UUIDT, group keys)
-- flow through without coercion.
--
-- DROP + ADD in a single ALTER keeps the column atomic from other sessions'
-- view: they see the table either with the old UUID column or with the new TEXT
-- column, never with no `person_id` at all. The dependent index is dropped here
-- and recreated CONCURRENTLY in the next migration.
SET lock_timeout = '5s';
ALTER TABLE cyclotron_jobs DROP COLUMN IF EXISTS person_id, ADD COLUMN person_id TEXT;
