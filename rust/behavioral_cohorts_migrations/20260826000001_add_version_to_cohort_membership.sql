-- The pipeline's canonical last-writer-wins version for a membership row: the producer's
-- monotonic `last_updated` stamp, the same value ClickHouse's ReplacingMergeTree orders on.
-- `last_updated` here stays consumer-write-time, so it cannot serve that role.
--
-- `-infinity` means "older than anything the pipeline has stamped", which is what pre-feature
-- rows are. NULL cannot carry that meaning: the sweep deletes rows matching `version < cutoff`,
-- and NULL fails that test, so the rows the sweep exists to delete would be the ones it never
-- sees. A constant default is catalog-only on PG 11+ (stored as attmissingval and synthesized at
-- read time), so NOT NULL here costs no rewrite, no backfill, and no validation scan.
--
-- Readers that format this column must handle the sentinel: `to_char` returns NULL for an
-- infinite timestamp instead of a formatted string.
--
-- The DDL is catalog-only, but it still takes a brief ACCESS EXCLUSIVE lock: queueing for it
-- behind a long-running statement parks every subsequent reader behind us. lock_timeout bounds
-- that wait; on timeout the per-file transaction aborts, nothing is recorded, and the next
-- migration run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cohort_membership ADD COLUMN IF NOT EXISTS version TIMESTAMP NOT NULL DEFAULT '-infinity';
