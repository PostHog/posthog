-- Create cohort membership table for behavioral cohorts
-- This table tracks which persons are members of which cohorts

CREATE TABLE IF NOT EXISTS cohort_membership (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL,
    cohort_id BIGINT NOT NULL,
    person_id UUID NOT NULL,
    in_cohort BOOLEAN NOT NULL,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add index on person_id, cohort_id, and team_id for query performance
CREATE INDEX IF NOT EXISTS idx_cohort_membership_lookup 
    ON cohort_membership (person_id, cohort_id, team_id);

-- Add unique constraint to prevent duplicate entries
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'cohort_membership_unique' 
        AND conrelid = 'cohort_membership'::regclass
    ) THEN
        ALTER TABLE cohort_membership 
        ADD CONSTRAINT cohort_membership_unique 
        UNIQUE (team_id, cohort_id, person_id);
    END IF;
END $$;