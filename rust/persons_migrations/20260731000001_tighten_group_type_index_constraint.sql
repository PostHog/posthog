-- Tighten posthog_grouptypemapping.group_type_index from <= 5 to <= 4.
--
-- ClickHouse's events table only has group0_* through group4_* columns
-- (posthog/models/event/sql.py) and HogQL's events schema stops at $group_4, so
-- index 5 has never been usable even though the check constraint allowed it.
-- Ingestion already refuses to allocate index 5 (MAX_GROUP_TYPES_PER_TEAM in
-- nodejs/src/common/groups/group-type-manager.ts), so no row should exist with
-- group_type_index = 5 — this migration fails loudly on `ADD CONSTRAINT` if one
-- does, rather than tightening silently over bad data.
--
-- This migration is idempotent and safe to re-run.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'group_type_index_is_less_than_or_equal_5'
        AND conrelid = 'posthog_grouptypemapping'::regclass
    ) THEN
        ALTER TABLE posthog_grouptypemapping DROP CONSTRAINT group_type_index_is_less_than_or_equal_5;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'group_type_index_is_less_than_or_equal_4'
        AND conrelid = 'posthog_grouptypemapping'::regclass
    ) THEN
        ALTER TABLE posthog_grouptypemapping ADD CONSTRAINT group_type_index_is_less_than_or_equal_4
            CHECK (group_type_index <= 4);
    END IF;
END $$;
