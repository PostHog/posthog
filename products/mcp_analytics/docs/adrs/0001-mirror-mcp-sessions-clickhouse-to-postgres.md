# ADR 0001 — Mirror MCP sessions from ClickHouse to Postgres

- **Status:** Accepted, tracks PR [#58407](https://github.com/PostHog/posthog/pull/58407).
- **Owner:** team-posthog-ai.
- **Related code:**
  - [`products/mcp_analytics/backend/models.py`](../../backend/models.py) — `MCPSession`.
  - [`posthog/temporal/mcp_analytics/backfill_sessions/`](../../../../posthog/temporal/mcp_analytics/backfill_sessions/) — `BackfillMCPSessionsWorkflow` and `aggregate_and_upsert_mcp_sessions` activity.

## Context

The session-list surface (`/mcp-analytics/sessions`) needs to render quickly, support search/filter, support pagination, support per-row joins to `Person` for identification, and feed sessions into the intent-clustering pipeline.

The raw signal is in ClickHouse: `mcp_tool_call` events on the `events` table, grouped by `$mcp_conversation_id`.
We considered two approaches:

1. **Query ClickHouse on every request.** Aggregate `mcp_tool_call` events by `$mcp_conversation_id` at read time, then join to Postgres `Person` for the identification piece.
2. **Maintain a Postgres mirror.** Run a periodic aggregate of ClickHouse `events`, upsert one row per `(team_id, session_id)` into a Postgres `MCPSession` table, and let the list view be a plain Django queryset over it.

## Decision

Maintain a Postgres mirror.

- Schema: [`MCPSession`](../../backend/models.py) — `team`, `session_id` (== `$mcp_conversation_id`), `session_start`, `session_end`, `duration_seconds`, `tools_used` (array), `tool_call_count`, `distinct_id`, `mcp_client_name`, `intent`. Unique on `(team, session_id)`, indexed by `(team, -session_end)`.
- Population: a Temporal workflow ([`BackfillMCPSessionsWorkflow`](../../../../posthog/temporal/mcp_analytics/backfill_sessions/workflow.py)) runs a single cross-team aggregate activity that does a **two-pass** ClickHouse query:
  1. Inner subquery — list `$mcp_conversation_id` values that have had any `mcp_tool_call` event in the last `lookback_hours`. These are the only sessions whose row could be stale.
  2. Outer query — re-aggregate the **full** history of each active conversation id, bounded by a `_RETENTION_DAYS = 7` window so the outer query can prune partitions.
- The activity calls `MCPSession.objects.unscoped().update_or_create(team_id=..., session_id=...)`. We deliberately use the unscoped manager because this is a cross-team activity; team scoping is encoded in the row, not in the queryset.

## Consequences

**Positive**

- Session-list pagination, search, ordering, and joins to `Person` are plain Django querysets. No bespoke HogQL per surface.
- Intent text and other LLM-derived fields can be persisted on the session row without a second store.
- Sessions are derived data: the table can be dropped and rebuilt from `events` by re-running the workflow. No primary-source contract to break.
- Two-pass aggregate keeps the ClickHouse read cheap: active session ids are computed in the inner subquery against a small lookback window, then the outer query only touches partitions for those ids over the retention window. A naive lookback-only aggregate would corrupt long-lived sessions when a late event lands — the two-pass aggregate cannot, because it always re-aggregates a session's full history once it's flagged active.

**Negative**

- Two stores for one logical entity. Bug surface area increases: schema drift, replication lag, partial backfills. A team that doesn't run the workflow will see an empty session list even with events flowing.
- `LIMIT 100000` on the aggregate query is a hard cap on active sessions per run. A team with a runaway agent could exceed it and silently lose the tail. We accept this for v1 and will revisit if any team approaches the limit.
- Conversation-id dependency. We key sessions on `$mcp_conversation_id` — if MCP clients stop populating it, the entire surface degrades. The inner subquery excludes empty conversation ids by construction, so the failure mode is "no sessions" rather than "one giant session", which is the right failure direction.

## Alternatives considered

- **Query ClickHouse on every request.** Rejected for v1 because (a) every join to `Person` would have to be done HogQL-side or stitched manually, (b) the session-list surface needs pagination/search/filter that are awkward to express against a rolling aggregate, and (c) intent text — which we want to persist next to the session — has nowhere obvious to live in this model. We could swap to this approach later if Postgres becomes a bottleneck, since events remain authoritative.
- **Front-end `$session_id` as the key.** Rejected. The MCP conversation is the unit of analysis; the browser session is not. A single agent conversation can span multiple browser sessions, or none at all (CLI agents).
- **Materialised view in ClickHouse.** Considered. Postponed because (a) we'd still need a Postgres layer for intent text and feedback joins, and (b) the operational cost of a new materialised view is higher than running a Temporal activity that re-aggregates a bounded, retention-day window. Worth revisiting if Postgres write throughput becomes the bottleneck.
