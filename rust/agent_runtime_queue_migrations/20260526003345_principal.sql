-- Add `principal` to agent_sessions.
--
-- The principal is the resolved caller identity stamped at session creation
-- (Layer 1 + Layer 2 of agent-stack/docs/auth-and-identity.md). Two shapes:
--
--   { "kind": "service", "orgId": "...", "caller": "..." }
--   { "kind": "user",    "spaceId": "...", "userId": "...",
--     "provider": "...", "providerAccountId": "...", "providerSubject": "..." }
--
-- NULL = the session was created under an `auth: public` agent with no
-- identity block — no principal to attribute it to.
--
-- agent-ingress reads it back on /listen /send /cancel to strict-match the
-- re-resolved caller against the session's stamped principal.

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS principal JSONB;
