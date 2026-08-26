-- The pipeline's canonical last-writer-wins version for a membership row: the producer's
-- monotonic `last_updated` stamp, the same value ClickHouse's ReplacingMergeTree orders on.
-- `last_updated` here stays consumer-write-time, so it cannot serve that role.
--
-- Nullable with no default keeps this an instant catalog-only DDL. A NULL version means
-- "older than anything the pipeline has stamped", which is what pre-feature rows are.
ALTER TABLE cohort_membership ADD COLUMN IF NOT EXISTS version TIMESTAMP;
