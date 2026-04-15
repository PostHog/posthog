-- Event subscriptions for the wait_until_event workflow step and event-based
-- conversion goals.
--
-- Split into two tables to avoid duplicating the step config (filters + bytecode)
-- across every person in a batch workflow. A single wait_until_event step with
-- a 100k-person cohort produces one definition row and 100k slim subscription
-- rows instead of 100k fat rows.
--
-- Definitions are shared across subscriptions for the same (hogflow, action,
-- config_version) and are upserted lazily the first time the handler creates
-- subscriptions referencing them.

CREATE TABLE IF NOT EXISTS cyclotron_event_subscription_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hogflow_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    filters JSONB,
    bytecode JSONB,
    content_hash TEXT NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hogflow_id, action_id, content_hash)
);

CREATE TABLE IF NOT EXISTS cyclotron_event_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES cyclotron_jobs(id) ON DELETE CASCADE,
    definition_id UUID NOT NULL REFERENCES cyclotron_event_subscription_definitions(id) ON DELETE CASCADE,
    team_id INT NOT NULL,
    person_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    type TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_event_subs_lookup
    ON cyclotron_event_subscriptions (team_id, event_name, person_id);

CREATE INDEX idx_event_subs_job
    ON cyclotron_event_subscriptions (job_id);

CREATE INDEX idx_event_subs_expires
    ON cyclotron_event_subscriptions (expires_at);
