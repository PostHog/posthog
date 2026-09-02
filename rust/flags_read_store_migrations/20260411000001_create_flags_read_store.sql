-- Replaces the earlier `flags_person_lookup` array-plus-GIN draft, which never ran
-- outside a local checkout. Near-unique distinct IDs behind an inverted index stall
-- on the GIN pending list, cannot enforce "one distinct ID maps to one person per
-- team", and couple the person and distinct ID write streams onto the same row. Two
-- PK btrees give both properties structurally and keep `person_uuid` remaps on the
-- mapping table HOT-eligible.

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

-- Both tables keep the default fillfactor. The benchmark sweeps `--person-fillfactor`
-- and `--map-fillfactor` to measure HOT headroom; ship a follow-up migration if the
-- sweep lands on a lower value.
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

-- The CDC consumer records the latest observed Kafka offset per source partition.
CREATE TABLE IF NOT EXISTS flags_read_store_heartbeat (
    source         TEXT        NOT NULL,
    partition      INTEGER     NOT NULL,
    last_offset    BIGINT      NOT NULL DEFAULT 0,
    last_event_ts  TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, partition)
);
