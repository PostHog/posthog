-- Versioned tombstones keep stale CDC replays from restoring deleted rows.
CREATE TABLE IF NOT EXISTS flags_person (
    team_id        INTEGER NOT NULL,
    person_uuid    UUID NOT NULL,
    properties     JSONB NOT NULL DEFAULT '{}'::JSONB,
    person_version BIGINT NOT NULL DEFAULT 0,
    deleted_at     TIMESTAMPTZ,
    PRIMARY KEY (team_id, person_uuid)
) PARTITION BY HASH (team_id);

CREATE TABLE IF NOT EXISTS flags_distinct_id_map (
    team_id    INTEGER NOT NULL,
    distinct_id TEXT NOT NULL,
    person_uuid UUID NOT NULL,
    version     BIGINT NOT NULL DEFAULT 0,
    deleted_at  TIMESTAMPTZ,
    PRIMARY KEY (team_id, distinct_id)
) PARTITION BY HASH (team_id);

DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS flags_person_p%s PARTITION OF flags_person FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS flags_distinct_id_map_p%s PARTITION OF flags_distinct_id_map FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

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
