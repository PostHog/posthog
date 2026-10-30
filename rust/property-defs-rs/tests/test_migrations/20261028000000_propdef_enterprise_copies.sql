-- Mirrors event_definitions migration 0017: the base table carries copies of the enterprise columns,
-- so a query that joins both tables has to qualify these names.
ALTER TABLE posthog_propertydefinition
    ADD COLUMN description text NULL,
    ADD COLUMN hidden boolean NULL,
    ADD COLUMN updated_at timestamp with time zone NULL,
    ADD COLUMN updated_by_id integer NULL,
    ADD COLUMN verified boolean NULL,
    ADD COLUMN verified_at timestamp with time zone NULL,
    ADD COLUMN verified_by_id integer NULL;
