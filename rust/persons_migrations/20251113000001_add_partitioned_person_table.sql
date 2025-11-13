-- Add partitioned person table
-- This creates a new person table partitioned by team_id using hash partitioning

CREATE TABLE IF NOT EXISTS posthog_person_new (
    LIKE posthog_person INCLUDING DEFAULTS
) PARTITION BY HASH (team_id);

-- Add primary key constraint that includes the partition key
ALTER TABLE posthog_person_new
    ADD CONSTRAINT posthog_person_new_pkey PRIMARY KEY (team_id, id);

-- Create index on uuid - must include team_id for partitioning
CREATE UNIQUE INDEX IF NOT EXISTS posthog_person_new_uuid_idx ON posthog_person_new (team_id, uuid);

-- Create 64 hash partitions
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS posthog_person_p%s PARTITION OF posthog_person_new FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

-- Drop foreign key constraints to allow writes to both old and new person tables
-- This is required during the migration period when persons may exist in either table
-- The index is kept for join performance

-- Drop FK from posthog_persondistinctid to posthog_person
ALTER TABLE posthog_persondistinctid
    DROP CONSTRAINT IF EXISTS posthog_persondistinctid_person_id_fkey;

-- Drop FK from posthog_featureflaghashkeyoverride to posthog_person
ALTER TABLE posthog_featureflaghashkeyoverride
    DROP CONSTRAINT IF EXISTS posthog_featureflaghashkeyoverride_person_id_fkey;

-- Drop FK from posthog_cohortpeople to posthog_person
ALTER TABLE posthog_cohortpeople
    DROP CONSTRAINT IF EXISTS posthog_cohortpeople_person_id_fkey;

-- Note: Indexes on person_id columns are preserved for join performance
-- - posthog_persondistinctid_person_id_5d655bba (kept)
-- - posthog_featureflaghashkeyoverride_person_id_7e517f7c (kept)
-- - posthog_cohortpeople_person_id_33da7d3f (kept)

