-- PersonHog person table: written by the personhog-writer service.
-- Mirrors posthog_person schema (minus is_user_id) with the same
-- hash-partitioning scheme so query patterns are identical.

CREATE TABLE IF NOT EXISTS personhog_person (
    id BIGINT NOT NULL,
    team_id INTEGER NOT NULL,
    uuid UUID NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    properties_last_updated_at JSONB,
    properties_last_operation JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    is_identified BOOLEAN NOT NULL DEFAULT false,
    last_seen_at TIMESTAMP WITH TIME ZONE
) PARTITION BY HASH (team_id);

ALTER TABLE personhog_person
    ADD CONSTRAINT personhog_person_pkey PRIMARY KEY (team_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS personhog_person_uuid_idx
    ON personhog_person (team_id, uuid);

-- 64 hash partitions matching the existing posthog_person scheme
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS personhog_person_p%s PARTITION OF personhog_person FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

-- Properties size check matching the existing constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'personhog_person_check_properties_size'
        AND conrelid = 'personhog_person'::regclass
    ) THEN
        ALTER TABLE personhog_person ADD CONSTRAINT personhog_person_check_properties_size
            CHECK (pg_column_size(properties) <= 655360) NOT VALID;
    END IF;
END $$;
