-- Initial v2 runtime schema. Established at the cutover from boot-time
-- SCHEMA_SQL → node-pg-migrate-managed migrations. Re-runs against an
-- existing prod DB are no-ops thanks to IF NOT EXISTS guards.

-- ---------------------------------------------------------------------
-- Runtime: agent_session
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_session (
    id              UUID PRIMARY KEY,
    application_id  UUID NOT NULL,
    revision_id     UUID NOT NULL,
    team_id         INT NOT NULL,
    external_key    TEXT,
    state           TEXT NOT NULL DEFAULT 'queued',
    conversation    JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_inputs  JSONB NOT NULL DEFAULT '[]'::jsonb,
    principal       JSONB,
    claimed_at      TIMESTAMPTZ,
    retry_count     INT NOT NULL DEFAULT 0,
    usage_total     JSONB NOT NULL DEFAULT '{
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost_input": 0,
        "cost_output": 0,
        "cost_cache_read": 0,
        "cost_cache_write": 0,
        "cost_total": 0
    }'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Catch up rows that predate `usage_total` on already-deployed instances.
ALTER TABLE agent_session
    ADD COLUMN IF NOT EXISTS usage_total JSONB NOT NULL DEFAULT '{
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost_input": 0,
        "cost_output": 0,
        "cost_cache_read": 0,
        "cost_cache_write": 0,
        "cost_total": 0
    }'::jsonb;

CREATE INDEX IF NOT EXISTS agent_session_state_created_idx
    ON agent_session (state, created_at);

CREATE INDEX IF NOT EXISTS agent_session_state_updated_idx
    ON agent_session (state, updated_at);

CREATE INDEX IF NOT EXISTS agent_session_external_key_idx
    ON agent_session (application_id, external_key)
    WHERE external_key IS NOT NULL;

-- ---------------------------------------------------------------------
-- Runtime: agent_user
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_user (
    id               UUID PRIMARY KEY,
    team_id          INT NOT NULL,
    application_id   UUID NOT NULL,
    principal_kind   TEXT NOT NULL,
    principal_id     TEXT NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_user_unique_natural_key
    ON agent_user (application_id, principal_kind, principal_id);

-- ---------------------------------------------------------------------
-- Runtime: agent_sandbox_instance
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_sandbox_instance (
    id                    UUID PRIMARY KEY,
    team_id               INT NOT NULL,
    application_id        UUID NOT NULL,
    revision_id           UUID NOT NULL,
    session_id            UUID,
    provider_kind         TEXT NOT NULL,
    provider_sandbox_id   TEXT NOT NULL DEFAULT '',
    state                 TEXT NOT NULL DEFAULT 'provisioning',
    error_message         TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at          TIMESTAMPTZ,
    terminated_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_state_idx
    ON agent_sandbox_instance (state, COALESCE(last_used_at, created_at));

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_session_idx
    ON agent_sandbox_instance (session_id) WHERE session_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- Authoring: agent_application + agent_revision
--
-- Prod runs these in Django's main DB via Django migrations. The test
-- harness uses a single DB and applies these here so PgRevisionStore can
-- read+write without needing two pools.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_application (
    id               UUID PRIMARY KEY,
    team_id          INT NOT NULL,
    slug             TEXT NOT NULL,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    encrypted_env    TEXT,
    live_revision_id UUID,
    archived         BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_application_unique_active_slug
    ON agent_application (team_id, slug) WHERE archived = FALSE;

CREATE TABLE IF NOT EXISTS agent_revision (
    id                 UUID PRIMARY KEY,
    application_id     UUID NOT NULL REFERENCES agent_application(id) ON DELETE CASCADE,
    parent_revision_id UUID,
    created_by_id      INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state              TEXT NOT NULL DEFAULT 'draft',
    bundle_uri         TEXT NOT NULL,
    bundle_sha256      TEXT,
    spec               JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS agent_revision_application_state_idx
    ON agent_revision (application_id, state);

-- Down migration intentionally omitted — agent-migrations is forward-only.
