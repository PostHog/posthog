-- Add covering indexes on the distinct id tables for the identity resolve.
--
-- resolve_distinct_ids is the hottest identity lookup: get_or_create and all
-- three merge paths run it on the primary pool. It joins a batch of
-- (team_id, distinct_id) keys against the distinct id table, then reads
-- person_id and is_deleted off the matched row. The unique
-- (team_id, distinct_id) index probes cleanly but carries no payload, so
-- every matched key costs a random heap fetch.
--
-- INCLUDE (person_id, is_deleted) lets the join leg run as an index-only scan:
-- both columns are read from the index leaf, so PostgreSQL skips the heap for
-- any page the visibility map marks all-visible. Distinct id UPDATEs clear
-- that bit, so the heap-free win holds only while autovacuum keeps the touched
-- pages all-visible; confirm on real batches with EXPLAIN (ANALYZE, BUFFERS)
-- that Heap Fetches stays low.
--
-- Both tables get the index. Identity currently points at the validation
-- shadow table (personhog_persondistinctid_tmp), and at
-- posthog_persondistinctid after cutover; the same statement runs against
-- whichever is configured.
--
-- NOT UNIQUE on purpose. Uniqueness of (team_id, distinct_id) is already
-- enforced by the existing unique index on each table, so this index only has
-- to cover the read.
--
-- LOCKING: a plain CREATE INDEX takes a SHARE lock that blocks writes for the
-- build, and the migration runner wraps each file in a transaction, so
-- CONCURRENTLY cannot be used here. On the large production
-- posthog_persondistinctid, build this index out-of-band and concurrently
-- FIRST; then IF NOT EXISTS makes this migration a no-op there. On fresh or
-- small databases (dev, CI, hobby) the inline build is cheap. Idempotent and
-- safe to re-run.

CREATE INDEX IF NOT EXISTS posthog_persondistinctid_team_distinct_covering_idx
    ON posthog_persondistinctid (team_id, distinct_id) INCLUDE (person_id, is_deleted);

CREATE INDEX IF NOT EXISTS personhog_persondistinctid_tmp_team_distinct_covering_idx
    ON personhog_persondistinctid_tmp (team_id, distinct_id) INCLUDE (person_id, is_deleted);
