---
name: querying-mcp-analytics-data
description: 'Query and interpret MCP analytics data — understand the event schema (mcp_tool_call, mcp_initialize), the $mcp_* property namespace, how sessions are grouped via $mcp_session_id, and how tool quality / intent clustering are derived. Use when writing HogQL against MCP events, debugging the MCP analytics product, building dashboards for MCP usage, or investigating why a session, tool call, or cluster looks the way it does in the MCP analytics UI.'
---

# Querying MCP analytics data

Use this skill when working with the events PostHog captures from MCP servers
instrumented with [`@posthog/mcp-analytics`](https://github.com/PostHog/mcp-analytics),
or when querying the denormalized session tables that the MCP analytics product reads from.

## Event vocabulary

The SDK emits standard MCP lifecycle events. The two that matter most are:

| Event            | Fired when                                              | Used by                                                     |
| ---------------- | ------------------------------------------------------- | ----------------------------------------------------------- |
| `mcp_initialize` | A client opens an MCP session (`initialize` JSON-RPC)   | Client / version breakdowns, "users and sessions" trends    |
| `mcp_tool_call`  | A tool is invoked on the server (`tools/call` JSON-RPC) | Session detail, tool quality, intent clustering, dashboards |

Every event carries the `$mcp_*` property namespace plus a standard `$session_id`.
`$ai_product = 'mcp'` is set on all events so they can be filtered alongside the rest of AI observability.

## The two session ids

This trips people up — read carefully.

- **`$mcp_session_id`** — the [Streamable-HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) transport session id, minted server-side and sent on every request via the `Mcp-Session-Id` header. Format is `uuid4`. **This is the canonical grouping key** for the MCP analytics Sessions tab and for the `posthog_mcp_session` table — a single MCP client connection = a single `$mcp_session_id`.
- **`$session_id`** — the standard PostHog session id (`uuid7`). Kept for Session Replay compatibility and consumer-side grouping when a wrapper app passes `?sessionId=`. Do **not** use this to group MCP tool calls into sessions — use `$mcp_session_id`.

Historical note: pre-#59506 the product grouped by `$mcp_conversation_id`. That property still exists in the schema but is scaffolded — it only populates once the calling agent echoes a conversation id (`@posthog/mcp-analytics` `enableConversationId: true`). Don't query it expecting values.

## Key `$mcp_*` properties

Pulled from `services/mcp/src/lib/posthog/analytics.ts:buildEventProperties` — that's the source of truth, check it if a property looks wrong.

**Per tool call**

- `$mcp_tool_name` — the tool the client invoked (e.g. `query_run`, `insight_get`)
- `$mcp_intent` — natural-language description the agent provided (powers intent clustering)
- `$mcp_is_error` — boolean; true if the tool call returned an error
- `$mcp_error_message` — error string when `$mcp_is_error` is true
- `$mcp_duration_ms` — server-side latency
- `$mcp_exec_tool_call_name` / `$mcp_exec_tool_call_description` — only set in `single-exec` mode, where the real tool name is wrapped inside an `exec` call

**Per session / connection**

- `$mcp_session_id` — see above
- `$mcp_client_name`, `$mcp_client_version`, `$mcp_client_user_agent` — the MCP client (Claude Desktop, Cursor, Windsurf, Cline, …)
- `$mcp_protocol_version` — MCP protocol revision (e.g. `2025-03-26`)
- `$mcp_transport` — `streamable_http`, `stdio`, etc.
- `$mcp_consumer`, `$mcp_mode` — wrapper-app context
- `$mcp_oauth_client_name`, `$mcp_read_only`, `$mcp_region`

**Per server identity**

- `$mcp_version`, `$mcp_organization_id`, `$mcp_project_id`, `$mcp_project_uuid`, `$mcp_project_name`

## Storage layout

There are two distinct surfaces — pick the right one for the query you're writing.

### ClickHouse `events` table

Raw `mcp_tool_call` / `mcp_initialize` events with all `$mcp_*` properties. Use this for:

- Trends, breakdowns, dashboards (the Dashboard tab is built from these)
- Tool quality (error rate, p50/p95 latency) — see `MCPAnalyticsToolQuality.tsx`
- Anything that needs per-call granularity

Example: tool error rate over the last 7 days, broken down by tool.

```sql
SELECT
    properties.$mcp_tool_name AS tool,
    countIf(toString(properties.$mcp_is_error) = 'true') / count() AS error_rate,
    count() AS calls
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool
ORDER BY calls DESC
```

### Postgres `posthog_mcp_session` table

Denormalized one-row-per-session view, maintained by the
[`backfill_sessions` Temporal workflow](../../backend/backfill_sessions/) and the
[`summarize_session_intents` workflow](../../backend/summarize_session_intents/).
Each row carries `session_id` (= `$mcp_session_id`), `session_start` / `session_end`,
`duration_seconds`, `tool_call_count`, `tools_used[]`, `distinct_id`, `mcp_client_name`,
and a summarised `intent` text. Use this when:

- Listing sessions in the UI
- Filtering / sorting by aggregate session attributes
- You need the LLM-generated session intent summary

To fetch the underlying tool calls for one session, join back to events via `$mcp_session_id`:

```sql
SELECT timestamp, properties.$mcp_tool_name, properties.$mcp_intent,
       properties.$mcp_is_error, properties.$mcp_duration_ms
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_session_id = {session_id}
ORDER BY timestamp ASC
```

This is exactly the query `list_mcp_tool_calls` in `backend/logic.py` runs.

## Intent clustering

Intent clustering operates on `$mcp_intent` strings grouped by `$session_id`
(yes, `$session_id` here, not `$mcp_session_id` — see the TODO in
`backend/intent_clustering.py`). The snapshot lives in
`posthog_mcp_analytics_intent_cluster_snapshot` as a JSON blob — one row per team.
When debugging "why is cluster X showing tool Y", read that JSON rather than re-deriving
from events.

## Common gotchas

- **`$mcp_is_error` is a string in ClickHouse.** Compare with `toString(...) = 'true'` or wrap in a boolean cast — `properties.$mcp_is_error = true` will not match.
- **Don't group by `distinct_id` to find sessions.** A single user can have many MCP sessions concurrently; `$mcp_session_id` is the only correct grouping key.
- **Person properties are point-in-time on events** (person-on-events mode is enabled). If you need the user's current name/email, resolve via the personhog client — never query `posthog_person` directly. See `posthog/personhog_client/README.md`.
- **The `MCPSession` row may not exist immediately.** It's populated by a Temporal workflow that runs periodically. For local dev, run `python manage.py seed_mcp_sessions --team-id <id>` to get fixture data without waiting.
- **Single-exec mode flattens tool names.** When `$mcp_mode = 'single-exec'`, every `$mcp_tool_name` is `exec`. The real tool is in `$mcp_exec_tool_call_name`. Always check `$mcp_mode` before aggregating by tool name in mixed populations.

## Where to look in the code

- Event property emission: `services/mcp/src/lib/posthog/analytics.ts`
- Session list / tool-call queries: `products/mcp_analytics/backend/logic.py`
- Session backfill (events → `MCPSession`): `products/mcp_analytics/backend/backfill_sessions/`
- Intent summarisation: `products/mcp_analytics/backend/summarize_session_intents/`
- Intent clustering: `products/mcp_analytics/backend/intent_clustering.py`
- Default dashboard insights: `products/mcp_analytics/backend/dashboard_templates.py`
- Local seeding: `products/mcp_analytics/backend/management/commands/seed_mcp_sessions.py`
