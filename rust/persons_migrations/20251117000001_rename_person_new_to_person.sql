-- Rename posthog_person_new to posthog_person (PoC migration)
-- This migration renames the new partitioned table to become the standard person table
-- The old table is preserved as posthog_person_old for rollback purposes
-- A compatibility view posthog_person_new is created to maintain backwards compatibility

BEGIN;

-- Lock both tables to prevent writes during the rename
LOCK TABLE posthog_person IN ACCESS EXCLUSIVE MODE;
LOCK TABLE posthog_person_new IN ACCESS EXCLUSIVE MODE;

-- Rename old table to posthog_person_old (preserves data for rollback)
ALTER TABLE posthog_person RENAME TO posthog_person_old;

-- Rename new partitioned table to posthog_person (becomes the active table)
ALTER TABLE posthog_person_new RENAME TO posthog_person;

-- Create view for backwards compatibility (allows code that references posthog_person_new to continue working)
CREATE VIEW posthog_person_new AS SELECT * FROM posthog_person;

COMMIT;
