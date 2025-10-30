CREATE TABLE posthog_errortrackingsymbolset (
    id UUID PRIMARY KEY,
    ref TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    storage_ptr TEXT,
    failure_reason TEXT,
    content_hash TEXT,
    release_id UUID,
    last_used TIMESTAMPTZ,
    CONSTRAINT unique_ref_per_team UNIQUE (team_id, ref)
);

-- Create index for team_id and ref combination
CREATE INDEX idx_error_tracking_symbol_sets_team_ref ON posthog_errortrackingsymbolset(team_id, ref);

CREATE TABLE IF NOT EXISTS posthog_errortrackingstackframe (
    id UUID PRIMARY KEY,
    raw_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    symbol_set_id UUID,
    contents JSONB NOT NULL,
    resolved BOOLEAN NOT NULL,
    context JSONB,
    part INTEGER,
    UNIQUE(raw_id, team_id)
);

CREATE TABLE IF NOT EXISTS posthog_errortrackingissue (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT,
    team_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS posthog_errortrackingissuefingerprintv2 (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fingerprint TEXT NOT NULL,
    version BIGINT NOT NULL,
    team_id INTEGER NOT NULL,
    issue_id UUID NOT NULL,
    UNIQUE(team_id, fingerprint)
);
