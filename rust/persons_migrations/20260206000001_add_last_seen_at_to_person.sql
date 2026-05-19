-- Add last_seen_at column to person table
-- This tracks when a person was last seen (last event timestamp)
--
-- SAFE: Adding nullable column without default is instant (metadata-only)
-- No table rewrite required regardless of table size
-- For partitioned tables, ALTER TABLE propagates to all partitions automatically

ALTER TABLE posthog_person
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
