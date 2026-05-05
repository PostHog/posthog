ALTER TABLE cyclotron_jobs ADD COLUMN person_id UUID;
ALTER TABLE cyclotron_jobs ADD COLUMN action_id TEXT;

CREATE INDEX idx_cyclotron_jobs_person_id
    ON cyclotron_jobs (team_id, person_id)
    WHERE person_id IS NOT NULL;
