/**
 * Postgres schema for the *runtime* side of the agent platform — the tables
 * the runner / ingress write to as agents execute. Authoring tables
 * (AgentApplication, AgentRevision) live in the main Django DB and are
 * created by Django migrations under `products/agent_stack/backend/`.
 *
 * Two distinct concerns, two distinct DBs in production:
 *   - posthog DB (Django ORM) — agent_application, agent_revision
 *   - queue DB (this schema)  — agent_session, agent_user,
 *                               agent_sandbox_instance
 *
 * Splitting them shields the main product DB from agent-runtime write load
 * (high-churn session updates, sandbox instance lifecycle). v1 used the same
 * split with `AGENT_RUNTIME_QUEUE_DATABASE_URL` for the queue tables.
 *
 * Tests / dev call `applySchema()` against a single fresh DB that holds
 * both sets of tables — see `agent-tests/src/harness/cluster.ts`.
 */

/**
 * Runtime-side schema. Applied by the worker at boot against the queue DB.
 * Idempotent.
 */
export const SCHEMA_SQL = `
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
    -- Number of times the janitor has re-queued this session after a stuck-
    -- running detection. Bounded by sweep policy (poison-pill threshold) —
    -- past the limit the session is marked failed instead of re-queued.
    retry_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_session_state_created_idx
    ON agent_session (state, created_at);

CREATE INDEX IF NOT EXISTS agent_session_state_updated_idx
    ON agent_session (state, updated_at);

CREATE INDEX IF NOT EXISTS agent_session_external_key_idx
    ON agent_session (application_id, external_key)
    WHERE external_key IS NOT NULL;

-- Stable identity for external users (Slack, IdP, etc.) interacting with an
-- agent. (application_id, principal_kind, principal_id) is the natural key.
-- The runtime side writes new rows whenever ingress sees an unfamiliar user;
-- ingress reads them to mint a stable AgentUser id per session.
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

-- Durable lifecycle log for tool sandboxes. Every container / Modal sandbox
-- the runner creates leaves a row here so a sibling worker (or the janitor)
-- can reap orphans after a crash. The Docker provider also has in-process
-- labels + an age-based reaper; this is the multi-worker view of the same
-- information.
CREATE TABLE IF NOT EXISTS agent_sandbox_instance (
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

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_state_idx
    ON agent_sandbox_instance (state, COALESCE(last_used_at, created_at));

CREATE INDEX IF NOT EXISTS agent_sandbox_instance_session_idx
    ON agent_sandbox_instance (session_id) WHERE session_id IS NOT NULL;
`

export const DROP_SQL = `
DROP TABLE IF EXISTS agent_sandbox_instance CASCADE;
DROP TABLE IF EXISTS agent_user CASCADE;
DROP TABLE IF EXISTS agent_session CASCADE;
`

/**
 * Authoring-side schema — the tables Django's `agent_stack` app owns. The
 * worker does not bootstrap these; production relies on Django migrations.
 * The test harness applies this against the same DB it uses for the queue
 * tables so the runner's `PgRevisionStore` can read+write without needing
 * two pools wired up for dev.
 */
export const AUTHORING_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS agent_application (
    id              UUID PRIMARY KEY,
    team_id         INT NOT NULL,
    slug            TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    encrypted_env   TEXT,
    live_revision_id UUID,
    archived        BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_application_unique_active_slug
    ON agent_application (team_id, slug) WHERE archived = FALSE;

CREATE TABLE IF NOT EXISTS agent_revision (
    id              UUID PRIMARY KEY,
    application_id  UUID NOT NULL REFERENCES agent_application(id) ON DELETE CASCADE,
    parent_revision_id UUID,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state           TEXT NOT NULL DEFAULT 'draft',
    bundle_uri      TEXT NOT NULL,
    bundle_sha256   TEXT,
    spec            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS agent_revision_application_state_idx
    ON agent_revision (application_id, state);
`

export const AUTHORING_DROP_SQL = `
DROP TABLE IF EXISTS agent_revision CASCADE;
DROP TABLE IF EXISTS agent_application CASCADE;
`
