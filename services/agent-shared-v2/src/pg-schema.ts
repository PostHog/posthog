/**
 * Postgres schema for the v2 agent platform. Idempotent — tests / dev call
 * `applySchema()` against a fresh database. Production uses Django migrations
 * derived from `products/agent_stack/backend/models_v2.py`.
 *
 * Caller passes a `Pool` from `pg`. We don't take a dep on `pg` directly — the
 * impls do, and tests / harnesses thread the pool through.
 */

export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS agent_application_v2 (
    id              UUID PRIMARY KEY,
    team_id         INT NOT NULL,
    slug            TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    encrypted_env   TEXT,
    live_revision_id UUID,
    archived        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_application_v2_unique_active_slug
    ON agent_application_v2 (team_id, slug) WHERE archived = FALSE;

CREATE TABLE IF NOT EXISTS agent_revision_v2 (
    id              UUID PRIMARY KEY,
    application_id  UUID NOT NULL REFERENCES agent_application_v2(id) ON DELETE CASCADE,
    parent_revision_id UUID,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state           TEXT NOT NULL DEFAULT 'draft',
    bundle_uri      TEXT NOT NULL,
    bundle_sha256   TEXT,
    spec            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS agent_revision_v2_application_state_idx
    ON agent_revision_v2 (application_id, state);

CREATE TABLE IF NOT EXISTS agent_session_v2 (
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
    -- Number of times the janitor has re-queued this session after a stuck-
    -- running detection. Bounded by sweep policy (poison-pill threshold) —
    -- past the limit the session is marked failed instead of re-queued.
    retry_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_session_v2_state_created_idx
    ON agent_session_v2 (state, created_at);

CREATE INDEX IF NOT EXISTS agent_session_v2_state_updated_idx
    ON agent_session_v2 (state, updated_at);

CREATE INDEX IF NOT EXISTS agent_session_v2_external_key_idx
    ON agent_session_v2 (application_id, external_key)
    WHERE external_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_user_v2 (
    id               UUID PRIMARY KEY,
    team_id          INT NOT NULL,
    application_id   UUID NOT NULL,
    principal_kind   TEXT NOT NULL,
    principal_id     TEXT NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_user_v2_unique_natural_key
    ON agent_user_v2 (application_id, principal_kind, principal_id);

-- Durable lifecycle log for tool sandboxes. Every Docker container / Modal
-- sandbox the runner creates leaves a row here so a sibling worker (or the
-- janitor) can reap orphans after a crash. The Docker provider also has
-- in-process labels + an age-based reaper; this layer is the multi-worker
-- view of the same information.
CREATE TABLE IF NOT EXISTS agent_sandbox_instance_v2 (
    id                    UUID PRIMARY KEY,
    team_id               INT NOT NULL,
    application_id        UUID NOT NULL,
    revision_id           UUID NOT NULL,
    session_id            UUID,
    provider_kind         TEXT NOT NULL,   -- 'in-process' | 'docker' | 'modal'
    provider_sandbox_id   TEXT NOT NULL DEFAULT '',
    state                 TEXT NOT NULL DEFAULT 'provisioning',
    error_message         TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at          TIMESTAMPTZ,
    terminated_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_v2_state_idx
    ON agent_sandbox_instance_v2 (state, COALESCE(last_used_at, created_at));

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_v2_session_idx
    ON agent_sandbox_instance_v2 (session_id) WHERE session_id IS NOT NULL;
`

export const DROP_SQL = `
DROP TABLE IF EXISTS agent_sandbox_instance_v2 CASCADE;
DROP TABLE IF EXISTS agent_user_v2 CASCADE;
DROP TABLE IF EXISTS agent_session_v2 CASCADE;
DROP TABLE IF EXISTS agent_revision_v2 CASCADE;
DROP TABLE IF EXISTS agent_application_v2 CASCADE;
`
