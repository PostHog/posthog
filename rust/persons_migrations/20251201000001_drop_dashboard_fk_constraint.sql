-- Drop foreign key constraint that shouldn't exist per Django model db_constraint=False
-- This constraint causes issues with cross-database relationships where GroupTypeMapping
-- (in persons_db) references Dashboard (in default db)
--
-- Background: Migration 0692_grouptypemapping_detail_dashboard.py created this constraint
-- when both tables were in the same database, but GroupTypeMapping was later moved to
-- persons_db while the constraint remained, causing FK validation failures.

ALTER TABLE posthog_grouptypemapping
    DROP CONSTRAINT IF EXISTS posthog_grouptypemapping_detail_dashboard_id_fk;
