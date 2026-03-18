-- Add grouping rule table for fingerprinting tests
CREATE TABLE IF NOT EXISTS posthog_errortrackinggroupingrule (
    id UUID PRIMARY KEY,
    team_id INTEGER NOT NULL,
    user_id INTEGER,
    role_id UUID,
    order_key INTEGER NOT NULL DEFAULT 0,
    bytecode JSONB NOT NULL,
    disabled_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_grouping_rule_team_id ON posthog_errortrackinggroupingrule(team_id);

-- Add assignment rule table for issue processing tests
CREATE TABLE IF NOT EXISTS posthog_errortrackingassignmentrule (
    id UUID PRIMARY KEY,
    team_id INTEGER NOT NULL,
    user_id INTEGER,
    role_id UUID,
    order_key INTEGER NOT NULL DEFAULT 0,
    bytecode JSONB NOT NULL,
    disabled_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assignment_rule_team_id ON posthog_errortrackingassignmentrule(team_id);
