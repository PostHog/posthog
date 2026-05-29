-- Slack user → PostHog user bridge (per-asker authorisation, #23 step 2).
--
-- When the ingress resolves a Slack identity to an AgentUser, it looks up
-- the Slack user's email via slack.users.info and matches to posthog_user.
-- The matched user_id is cached here so subsequent events skip the lookup
-- and the dispatcher (step 3) can synchronously read the posthog user.
--
-- Nullable: not every Slack user maps to a PostHog user — external Slack
-- members who don't have a posthog_user row stay unmapped, and the
-- dispatcher's per-asker check falls back to "needs approval" for them.

ALTER TABLE agent_user
    ADD COLUMN IF NOT EXISTS posthog_user_id INTEGER;

-- Down migration intentionally omitted — agent-migrations is forward-only.
