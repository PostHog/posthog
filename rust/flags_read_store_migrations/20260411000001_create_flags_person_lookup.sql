-- One row per person, keyed on (team_id, person_uuid), with a distinct_ids TEXT[]
-- column indexed by GIN so the flags service can replace its two-table JOIN with a
-- single PK / GIN read. HASH-partitioned by team_id (64 partitions) to mirror the
-- posthog_person table in the shared persons database.

-- btree_gin is required so the GIN index can include the scalar team_id column
-- alongside the distinct_ids array. A single hash partition can hold rows from
-- multiple teams, so keeping team_id in the GIN index is necessary for selective
-- lookups within a partition.
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- `deleted_at` keeps tombstoned rows around so the upsert's version guard
-- still has a row to compare against and can reject stale PersonUpdate
-- messages arriving after a delete. Reads must filter `deleted_at IS NULL`.
CREATE TABLE IF NOT EXISTS flags_person_lookup (
    team_id              INTEGER NOT NULL,
    person_uuid          UUID NOT NULL,
    distinct_ids         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    properties           JSONB NOT NULL DEFAULT '{}'::jsonb,
    person_version       BIGINT NOT NULL DEFAULT 0,
    distinct_id_version  BIGINT NOT NULL DEFAULT 0,
    deleted_at           TIMESTAMPTZ,
    PRIMARY KEY (team_id, person_uuid)
) PARTITION BY HASH (team_id);

-- Create 64 hash partitions. This matches posthog_person's partition count so the
-- two tables stay aligned for future bootstrap / hash key override work.
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS flags_person_lookup_p%s PARTITION OF flags_person_lookup FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

-- GIN index on (team_id, distinct_ids), partial on live rows. Postgres propagates
-- the index definition to every hash partition automatically. The partial predicate
-- mirrors the read-path filter so tombstoned rows never produce GIN entries, which
-- shrinks the index and avoids write amplification as deletions accumulate.
CREATE INDEX IF NOT EXISTS idx_flags_person_gin
    ON flags_person_lookup
    USING GIN (team_id, distinct_ids)
    WHERE deleted_at IS NULL;

-- Heartbeat / lag-monitoring table. The CDC consumer will write one row per (source, partition) with
-- the last Kafka offset / event timestamp it processed; the shadow read path will
-- join against this for staleness checks. Table-only in Step 1; no writes yet.
CREATE TABLE IF NOT EXISTS flags_read_store_heartbeat (
    source         TEXT        NOT NULL,
    partition      INTEGER     NOT NULL,
    last_offset    BIGINT      NOT NULL DEFAULT 0,
    last_event_ts  TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, partition)
);
