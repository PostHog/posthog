-- Parking for lifecycle ops the leader has definitively refused.
--
-- A semantic refusal (the leader rejecting the request itself) cannot be
-- outlived by retries: the sweeper skips parked ops instead of retrying
-- them forever, and an explicit retry with the same op_id claims,
-- un-parks, and re-drives once the cause is fixed.
--
-- SAFE: adds nullable columns to a small saga-state table; takes only a
-- brief ACCESS EXCLUSIVE lock with no rewrite. Idempotent and safe to
-- re-run.

ALTER TABLE lifecycle_op
    ADD COLUMN IF NOT EXISTS parked_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS parked_reason TEXT;
