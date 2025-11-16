-- Swap person tables: make partitioned table the primary one
-- This migration renames the unpartitioned posthog_person to posthog_person_old
-- and renames the partitioned posthog_person_new to posthog_person

-- Rename unpartitioned table out of the way
ALTER TABLE IF EXISTS posthog_person RENAME TO posthog_person_old;

-- Rename partitioned table to primary name
ALTER TABLE IF EXISTS posthog_person_new RENAME TO posthog_person;
