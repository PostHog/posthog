CREATE TABLE posthog_errortrackingrelease (
    id UUID PRIMARY KEY,
    team_id INTEGER NOT NULL,
    hash_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    version VARCHAR(255) NOT NULL,
    project VARCHAR(255) NOT NULL,
    metadata JSONB
);
