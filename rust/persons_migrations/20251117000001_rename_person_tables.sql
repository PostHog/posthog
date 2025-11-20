-- Rename person tables to use partitioned table as primary
-- This makes posthog_person point to the partitioned table

-- Rename old table to posthog_person_old
ALTER TABLE IF EXISTS posthog_person RENAME TO posthog_person_old;

-- Rename new partitioned table to posthog_person
ALTER TABLE IF EXISTS posthog_person_new RENAME TO posthog_person;

-- Create view for backwards compatibility with Rust code
CREATE OR REPLACE VIEW posthog_person_new AS SELECT * FROM posthog_person;
