-- Temporary validation table for the personhog-writer service.
--
-- This table mirrors posthog_person (minus is_user_id) and is used during the
-- validation phase to verify that personhog's write pipeline produces correct
-- person state. It is NOT the production write target.
--
-- Once validation is complete and we're ready to cut over, the writer switches
-- to writing directly to posthog_person (via PG_TARGET_TABLE config), and this
-- table can be dropped.
--
-- This migration is idempotent and safe to re-run.

CREATE SEQUENCE IF NOT EXISTS personhog_person_tmp_id_seq;

CREATE TABLE IF NOT EXISTS personhog_person_tmp (
    id BIGINT NOT NULL DEFAULT nextval('personhog_person_tmp_id_seq'),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    properties_last_updated_at JSONB,
    properties_last_operation JSONB,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_identified BOOLEAN NOT NULL DEFAULT false,
    uuid UUID NOT NULL,
    version BIGINT,
    team_id INTEGER NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE
) PARTITION BY HASH (team_id);

-- Tie the sequence lifecycle to the table so DROP TABLE also drops the
-- sequence. Idempotent — re-running with the same owner is a no-op.
ALTER SEQUENCE personhog_person_tmp_id_seq OWNED BY personhog_person_tmp.id;

-- Primary key (idempotent: only add if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'personhog_person_tmp_pkey'
        AND conrelid = 'personhog_person_tmp'::regclass
    ) THEN
        ALTER TABLE personhog_person_tmp
            ADD CONSTRAINT personhog_person_tmp_pkey PRIMARY KEY (team_id, id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS personhog_person_tmp_uuid_idx
    ON personhog_person_tmp (team_id, uuid);

-- 64 hash partitions matching the existing posthog_person scheme
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS personhog_person_tmp_p%s PARTITION OF personhog_person_tmp FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

-- Properties size check matching the existing constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'personhog_person_tmp_check_properties_size'
        AND conrelid = 'personhog_person_tmp'::regclass
    ) THEN
        ALTER TABLE personhog_person_tmp ADD CONSTRAINT personhog_person_tmp_check_properties_size
            CHECK (pg_column_size(properties) <= 655360) NOT VALID;
    END IF;
END $$;
