-- Swap person tables: make partitioned table the primary one
-- Production already has posthog_person_new (partitioned), this migration makes it the main table
-- and renames the old unpartitioned table out of the way.

-- Rename old unpartitioned table out of the way
ALTER TABLE IF EXISTS posthog_person RENAME TO posthog_person_old;

-- Rename new (partitioned) table to primary name
ALTER TABLE IF EXISTS posthog_person_new RENAME TO posthog_person;

-- Create empty posthog_person_new for compatibility (in case any code still references it)
-- This won't be actively used, but allows for zero-downtime switchover
CREATE TABLE IF NOT EXISTS posthog_person_new (LIKE posthog_person INCLUDING ALL);
