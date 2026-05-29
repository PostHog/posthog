-- Per-session ACL + pending elevation requests. See
-- docs/agent-platform/plans/per-session-access-elevation.md.
--
-- The ACL is an allowlist of additional principals (or scopes) on top of the
-- session's primary `principal`. v0 ships with the storage and the enforcement
-- check — no UI yet — so this column stays empty in practice until v1 lands
-- the grant surface. `pending_elevation_requests` records denied attempts so
-- the v1 UI has the data to render an elevation prompt.

ALTER TABLE agent_session
    ADD COLUMN IF NOT EXISTS acl JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE agent_session
    ADD COLUMN IF NOT EXISTS pending_elevation_requests JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Down migration intentionally omitted — agent-migrations is forward-only.
