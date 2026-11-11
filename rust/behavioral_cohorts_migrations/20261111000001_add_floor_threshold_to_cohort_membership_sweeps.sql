-- The run's sweep threshold, frozen by its first claim. The floor records the sweeper publishes
-- to the membership topic and every delete page use this one value, so a snapshot or marker
-- minimum that moves after the claim cannot make Postgres delete a different set than the
-- floor already in the log. NULL until the first claim.
--
-- Adding a nullable column with no default is catalog-only, but it still takes a brief ACCESS
-- EXCLUSIVE lock, and the membership consumer writes this table inside its batch transactions.
-- lock_timeout bounds the wait. On timeout the per-file transaction aborts, nothing is recorded,
-- and the next migration run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cohort_membership_sweeps ADD COLUMN IF NOT EXISTS floor_threshold TIMESTAMP;
