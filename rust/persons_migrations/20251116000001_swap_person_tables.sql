-- Swap person tables: make partitioned table the primary one
-- Production already has posthog_person_new (partitioned), this migration makes it the main table
-- and renames the old unpartitioned table out of the way.

-- Rename old unpartitioned table out of the way (if it exists - it might not in fresh installs)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'posthog_person'
        AND table_type = 'BASE TABLE'
    ) THEN
        -- Check if it's not partitioned (old table)
        IF NOT EXISTS (
            SELECT 1 FROM pg_partitioned_table
            WHERE relid = 'public.posthog_person'::regclass
        ) THEN
            ALTER TABLE posthog_person RENAME TO posthog_person_old;
        END IF;
    END IF;
END $$;

-- Rename new (partitioned) table to primary name
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'posthog_person_new'
    ) THEN
        ALTER TABLE posthog_person_new RENAME TO posthog_person;
    END IF;
END $$;
