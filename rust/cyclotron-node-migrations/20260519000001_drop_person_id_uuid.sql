-- The wait-until-event feature is not yet live, so we drop existing data and
-- re-add the column as TEXT so non-UUID person identifiers (UUIDT, group keys)
-- flow through without coercion. Dropping the column also drops the dependent
-- index, which is rebuilt in a later migration.
ALTER TABLE cyclotron_jobs DROP COLUMN IF EXISTS person_id;
