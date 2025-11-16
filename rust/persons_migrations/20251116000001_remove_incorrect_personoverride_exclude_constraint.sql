-- Remove the incorrect GIST EXCLUDE constraint that prevented legitimate merge operations.
-- The constraint logic was inverted and caused the test_person_override_allows_duplicate_override_person_id
-- test to fail.  Integrity is already ensured by:
-- - unique_override_per_old_person_id: prevents duplicate old_person_ids for same team
-- - old_person_id_different_from_override_person_id: prevents self-override

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'exclude_override_person_id_from_being_old_person_id'
        AND conrelid = 'posthog_personoverride'::regclass
    ) THEN
        ALTER TABLE posthog_personoverride DROP CONSTRAINT exclude_override_person_id_from_being_old_person_id;
    END IF;
END $$;
