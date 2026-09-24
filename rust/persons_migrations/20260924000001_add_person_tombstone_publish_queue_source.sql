-- Names the writer of each person_tombstone_publish_queue row.
--
-- The queue started as the GDPR delete path's record of a ClickHouse tombstone that is
-- not yet confirmed. Ingestion merges now record their source-person deletions the same
-- way, and each writer republishes only its own rows, so the two retry loops stay apart.
-- Rows written before this column keep a NULL source and belong to the delete path.
--
-- SAFE: adds a nullable column with no default and one partial index; takes no
-- table rewrite. Idempotent and safe to re-run.

ALTER TABLE person_tombstone_publish_queue
    ADD COLUMN IF NOT EXISTS source TEXT;

CREATE INDEX IF NOT EXISTS person_tombstone_publish_queue_source_pending
    ON person_tombstone_publish_queue (source, tombstoned_at)
    WHERE given_up_at IS NULL;

COMMENT ON COLUMN person_tombstone_publish_queue.source IS
    'Writer of the row: ingestion-merge for a merge source deletion, NULL for the delete path.';
