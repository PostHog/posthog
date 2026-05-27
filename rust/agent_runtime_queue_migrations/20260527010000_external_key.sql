-- Add `external_key` to agent_sessions.
--
-- A free-form string an external system can use to look up an active
-- session. The trigger that creates a session sets it; later requests
-- from the same external system compute the same key and reuse the
-- session instead of spawning a new one. Generic on purpose: today's
-- Slack thread binding ("slack:<workspace>:<channel>:<thread_ts>:<user>")
-- is one shape; an email-thread bridge or any future webhook entrypoint
-- can pick its own scheme.
--
-- Format convention (NOT enforced at the DB):
--   "<provider>:<provider-specific-tuple>"
-- e.g. "slack:T_OWNER:C_THREAD:1735000000.001234:U_OWNER"
--
-- Uniqueness is partial: a key only conflicts with another ACTIVE
-- session for the same (team, application). Terminal sessions
-- (completed / failed / canceled) don't block a fresh session under
-- the same key, so a new mention in a previously-closed thread spawns
-- a clean session.

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS external_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS agent_sessions_external_key_active
    ON agent_sessions (team_id, application_id, external_key)
    WHERE external_key IS NOT NULL
      AND status IN ('available', 'running');

-- Plain lookup index for the active-session resolver. Partial unique
-- above already covers the (team, app, key) ON-non-terminal path; this
-- is just for the SELECT used by ingress to find the row to /send to.
CREATE INDEX IF NOT EXISTS agent_sessions_external_key_lookup
    ON agent_sessions (team_id, application_id, external_key)
    WHERE external_key IS NOT NULL;
