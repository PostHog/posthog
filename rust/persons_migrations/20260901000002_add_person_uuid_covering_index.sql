-- Add a covering index on posthog_person for uuid -> id resolution.
--
-- The delete path (and the pg-cleanup drain) resolves person UUIDs to integer
-- ids with WHERE team_id = $1 AND uuid = ANY($2). team_id prunes to one hash
-- partition and each uuid is a clean probe of the unique (team_id, uuid) index,
-- but that index does not carry id, so every matched uuid costs a random heap
-- fetch. At up to 1000 uuids per call this is the dominant cost of the resolve.
--
-- INCLUDE (id) lets the resolve run as an index-only scan: id is read from the
-- index leaf, so PostgreSQL skips the heap for any page the visibility map marks
-- all-visible. Person UPDATEs clear that bit, so the heap-free win holds only
-- while autovacuum keeps the touched pages all-visible; confirm on real batches
-- with EXPLAIN (ANALYZE, BUFFERS) that Heap Fetches stays low.
--
-- This UNIQUE index enforces the same (team_id, uuid) constraint as the existing
-- unique index, so the older one is now redundant and can be dropped out-of-band
-- once this index is live in every environment. It is left in place here because
-- its name differs across environments (posthog_person_new_uuid_idx in
-- migration-built databases, posthog_person_team_id_uuid_uniq in prod-US/EU), so
-- a portable migration cannot reference it safely.
--
-- LOCKING: a plain CREATE INDEX takes a SHARE lock that blocks writes for the
-- build. On the large production posthog_person table, build this index
-- out-of-band and concurrently per partition first; then IF NOT EXISTS makes this
-- migration a no-op there. On fresh or small databases (dev, CI, hobby) the
-- inline build is cheap. Idempotent and safe to re-run.

CREATE UNIQUE INDEX IF NOT EXISTS posthog_person_team_id_uuid_covering_idx
    ON posthog_person (team_id, uuid) INCLUDE (id);
