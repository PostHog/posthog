-- Add group key columns to person table
-- These columns store the group keys (e.g. company name) that a person belongs to,
-- enabling JOINs from persons to groups for mixed user+group flag targeting.
--
-- SAFE: Adding columns with defaults is instant in Postgres 11+ (metadata-only)
-- No table rewrite required regardless of table size
-- For partitioned tables, ALTER TABLE propagates to all partitions automatically

ALTER TABLE posthog_person ADD COLUMN IF NOT EXISTS group_0_key VARCHAR(400) NOT NULL DEFAULT '';
ALTER TABLE posthog_person ADD COLUMN IF NOT EXISTS group_1_key VARCHAR(400) NOT NULL DEFAULT '';
ALTER TABLE posthog_person ADD COLUMN IF NOT EXISTS group_2_key VARCHAR(400) NOT NULL DEFAULT '';
ALTER TABLE posthog_person ADD COLUMN IF NOT EXISTS group_3_key VARCHAR(400) NOT NULL DEFAULT '';
ALTER TABLE posthog_person ADD COLUMN IF NOT EXISTS group_4_key VARCHAR(400) NOT NULL DEFAULT '';
