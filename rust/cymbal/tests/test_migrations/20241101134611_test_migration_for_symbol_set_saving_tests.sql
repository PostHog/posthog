CREATE TABLE posthog_errortrackingsymbolset (
    id UUID PRIMARY KEY,
    ref TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    storage_ptr TEXT,
    failure_reason TEXT,
    CONSTRAINT unique_ref_per_team UNIQUE (team_id, ref)
);

-- Create index for team_id and ref combination
CREATE INDEX idx_error_tracking_symbol_sets_team_ref ON posthog_errortrackingsymbolset(team_id, ref);

-- Add migration script here
CREATE TABLE IF NOT EXISTS posthog_errortrackingstackframe (
    id UUID PRIMARY KEY,
    raw_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    symbol_set_id UUID,
    contents JSONB NOT NULL,
    resolved BOOLEAN NOT NULL,
    UNIQUE(raw_id, team_id)
);
