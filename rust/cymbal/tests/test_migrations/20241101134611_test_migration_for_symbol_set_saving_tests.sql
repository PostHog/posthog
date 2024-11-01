CREATE TABLE posthog_errortrackingsymbolset (
    id UUID PRIMARY KEY,
    ref TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    storage_ptr TEXT,
    CONSTRAINT unique_ref_per_team UNIQUE (team_id, ref)
);

-- Create index for team_id and ref combination
CREATE INDEX idx_error_tracking_symbol_sets_team_ref ON posthog_errortrackingsymbolset(team_id, ref);
