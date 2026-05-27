-- Add `pending_inputs` to agent_sessions.
--
-- Stores the queue of user messages received via `/send/:id` while the
-- session is parked between turns. Today the runner suspends on an
-- in-process Promise and the Redis bus carries the message; if the
-- worker dies the message is lost. With this column, every `/send`
-- writes durably here first; the worker drains it on the next turn.
--
-- Shape: `[{ at: "ISO", content: "text" }, ...]`. Append-on-receive,
-- drain-on-turn-start. Stored as JSONB (not packed into `state` BYTEA)
-- so an `/send` append doesn't race with the worker rewriting `state`
-- — concurrent updates touch disjoint columns.

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS pending_inputs JSONB NOT NULL DEFAULT '[]'::jsonb;
