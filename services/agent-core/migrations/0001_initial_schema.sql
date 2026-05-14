-- agent_sessions: durable record of a single session execution.
-- Lives in a dedicated Postgres DB (agent_runtime_queue). The team-scoped mirror row
-- in main posthog Postgres (AgentSession) carries FKs to Team/AgentApplication/Revision.

CREATE TYPE AgentSessionStatus AS ENUM(
    'available',
    'running',
    'completed',
    'failed',
    'canceled'
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    application_id UUID,
    revision_id UUID,
    queue_name TEXT NOT NULL,
    status AgentSessionStatus NOT NULL,
    scheduled TIMESTAMPTZ NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    lock_id UUID,
    last_heartbeat TIMESTAMPTZ,
    janitor_touch_count SMALLINT NOT NULL DEFAULT 0,
    transition_count SMALLINT NOT NULL DEFAULT 0,
    last_transition TIMESTAMPTZ NOT NULL,
    state BYTEA,
    state_byte_size INT
);

-- Dequeue path
CREATE INDEX idx_agent_sessions_dequeue
    ON agent_sessions (queue_name, scheduled)
    WHERE status = 'available';

-- Janitor: stalled running jobs
CREATE INDEX idx_agent_sessions_stalled
    ON agent_sessions (last_heartbeat)
    WHERE status = 'running';

-- Janitor: terminal jobs awaiting cleanup
CREATE INDEX idx_agent_sessions_terminal
    ON agent_sessions (last_transition)
    WHERE status IN ('completed', 'failed', 'canceled');

CREATE INDEX idx_agent_sessions_team_id ON agent_sessions(team_id);
CREATE INDEX idx_agent_sessions_revision_id ON agent_sessions(revision_id);
CREATE INDEX idx_agent_sessions_application_id ON agent_sessions(application_id);

-- Bookkeeping so we can apply migrations idempotently.
CREATE TABLE IF NOT EXISTS agent_runtime_migrations (
    id TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
