-- General-purpose `idempotency_key` on agent_session — see
-- docs/agent-platform/plans/cron-trigger-scheduler.md §6.
--
-- Semantically distinct from `external_key`:
--   external_key      = "same conversation thread" (collision → append to
--                       pending_inputs, session continues).
--   idempotency_key   = "same request" (collision → no-op, return the
--                       original session id; Stripe-shaped). Cleared by a
--                       janitor sweep after ~30 days.
--
-- Both fields are independent; a session can have both. The partial unique
-- index enforces "at most one live session per (application, idempotency_key)"
-- without forcing every session to carry a key.
--
-- v0 consumers:
--   - cron firings: idempotencyKey = `cron:<rev>:<name>:<minute>` so two
--     janitor replicas can't both create a session for the same firing.
--   - webhook redeliveries: provider-supplied keys (Stripe `idempotency_key`,
--     `X-Hub-Signature-ID`, Slack retry headers) prevent double-delivery.
--
-- `trigger_metadata` is the companion JSONB column — carries
-- `{ kind, cron_name, schedule, fired_at }` for cron firings (and analogous
-- payloads for other triggers). Surfaces on session-detail UI per plan §9
-- "Observability"; replaces the alternative of stashing it inside the user
-- message blob.

ALTER TABLE agent_session
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

ALTER TABLE agent_session
    ADD COLUMN IF NOT EXISTS trigger_metadata JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS agent_session_idempotency_key_unique
    ON agent_session (application_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
