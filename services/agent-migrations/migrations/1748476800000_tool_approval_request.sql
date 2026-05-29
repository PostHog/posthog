-- Approval-gated tool calls. See docs/agent-platform/plans/approval-gated-tools.md.
--
-- One row per intercepted gated tool call. Sessions do NOT park — the model
-- sees a synthetic queued tool_result with an approval link and keeps
-- running. The approval API and the janitor expiry sweep update state and
-- stamp the dispatch outcome here.

CREATE TABLE IF NOT EXISTS agent_tool_approval_request (
    id                 UUID PRIMARY KEY,
    session_id         UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    application_id     UUID NOT NULL,
    team_id            BIGINT NOT NULL,
    revision_id        UUID NOT NULL,
    turn               INT NOT NULL,
    tool_call_id       TEXT NOT NULL,
    tool_name          TEXT NOT NULL,
    proposed_args      JSONB NOT NULL,
    args_hash          BYTEA NOT NULL,
    -- Snapshot of the assistant message that emitted the call. Keeps the
    -- approver UI whole even if conversation compaction truncates the
    -- original session log later.
    assistant_message  JSONB NOT NULL,
    approver_scope     JSONB NOT NULL,
    state              TEXT NOT NULL CHECK (state IN (
        'queued',
        'approving',
        'dispatched',
        'dispatched_failed',
        'rejected',
        'expired'
    )),
    decision_by        UUID NULL,
    decision_at        TIMESTAMPTZ NULL,
    decision_reason    TEXT NULL,
    decided_args       JSONB NULL,
    dispatch_outcome   JSONB NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at         TIMESTAMPTZ NOT NULL
);

-- Idempotency: only one queued row per (session, tool, canonical args).
-- After a terminal decision the model can re-issue and a fresh row inserts.
CREATE UNIQUE INDEX IF NOT EXISTS agent_tool_approval_request_queued_unique
    ON agent_tool_approval_request (session_id, tool_name, args_hash)
    WHERE state = 'queued';

-- Janitor sweep over queued rows past their TTL.
CREATE INDEX IF NOT EXISTS agent_tool_approval_request_expiry_idx
    ON agent_tool_approval_request (state, expires_at);

-- Team-level inbox listings.
CREATE INDEX IF NOT EXISTS agent_tool_approval_request_team_idx
    ON agent_tool_approval_request (team_id, state, created_at DESC);

-- Per-agent listings.
CREATE INDEX IF NOT EXISTS agent_tool_approval_request_app_idx
    ON agent_tool_approval_request (application_id, state, created_at DESC);

-- Session-detail listings.
CREATE INDEX IF NOT EXISTS agent_tool_approval_request_session_idx
    ON agent_tool_approval_request (session_id, created_at DESC);

-- Down migration intentionally omitted — agent-migrations is forward-only.
