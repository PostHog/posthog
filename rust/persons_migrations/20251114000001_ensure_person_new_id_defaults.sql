-- Ensure posthog_person_new partitions have proper ID defaults
-- This handles both production (explicit sequence) and test (identity) cases

DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
    partition_name TEXT;
    max_id BIGINT;
    sequence_exists BOOLEAN;
BEGIN
    -- Check if posthog_person_id_seq exists (production case with explicit sequence)
    SELECT EXISTS (
        SELECT 1 FROM pg_sequences WHERE sequencename = 'posthog_person_id_seq'
    ) INTO sequence_exists;

    -- If sequence doesn't exist, create it from identity or fresh
    IF NOT sequence_exists THEN
        -- Check if posthog_person uses identity (test case)
        IF EXISTS (
            SELECT 1 FROM pg_attribute
            WHERE attrelid = 'posthog_person'::regclass
            AND attname = 'id'
            AND attidentity != ''
        ) THEN
            -- Get the identity sequence name and rename it
            EXECUTE format(
                'ALTER SEQUENCE %I RENAME TO posthog_person_id_seq',
                pg_get_serial_sequence('posthog_person', 'id')
            );
        ELSE
            -- No existing sequence, create new one
            CREATE SEQUENCE posthog_person_id_seq;

            -- Set it to max ID from old table if data exists
            EXECUTE 'SELECT COALESCE(MAX(id), 0) FROM posthog_person' INTO max_id;
            IF max_id > 0 THEN
                PERFORM setval('posthog_person_id_seq', max_id, true);
            END IF;
        END IF;
    END IF;

    -- Set the default on the parent table (not partitions)
    -- For partitioned tables, defaults must be on the parent to work with INSERT
    ALTER TABLE posthog_person_new ALTER COLUMN id SET DEFAULT nextval('posthog_person_id_seq');

    -- Sync sequence to max ID across all partitions
    max_id := 0;
    FOR i IN 0..(num_partitions - 1) LOOP
        partition_name := 'posthog_person_p' || i;
        EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I', partition_name) INTO max_id;
        IF max_id > 0 AND max_id > (SELECT last_value FROM posthog_person_id_seq) THEN
            PERFORM setval('posthog_person_id_seq', max_id, true);
        END IF;
    END LOOP;
END $$;
