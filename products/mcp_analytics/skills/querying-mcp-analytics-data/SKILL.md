---
name: querying-mcp-analytics-data
description: 'Query and interpret MCP analytics data — answer questions about MCP tool usage, error rates, latency, session counts, or which clients and tools are most used. Covers the event schema (mcp_initialize, mcp_tools_list, mcp_tool_call), the $mcp_* property namespace, the three grouping ids ($mcp_conversation_id for stable cross-reconnect grouping, $mcp_session_id for raw transport sessions), the cli-mode gotcha where every $mcp_tool_name is "exec" (the real inner tool lives in $mcp_exec_tool_call_name), and how tool quality and intent clustering are derived. Use when writing HogQL against MCP events, ranking or counting MCP tools or clients, building dashboards for MCP usage, debugging the MCP analytics product, or investigating why a session, tool call, or cluster looks the way it does in the MCP analytics UI.'
---

# Querying MCP analytics data

Use this skill when working with the events PostHog captures from MCP servers
instrumented with [`@posthog/mcp-analytics`](https://github.com/PostHog/mcp-analytics),
or when querying the denormalized session tables that the MCP analytics product reads from.

## Event vocabulary

The SDK emits standard MCP lifecycle events. The three that matter most are:

| Event            | Fired when                                              | Used by                                                     |
| ---------------- | ------------------------------------------------------- | ----------------------------------------------------------- |
| `mcp_initialize` | A client opens an MCP session (`initialize` JSON-RPC)   | Client / version breakdowns, "users and sessions" trends    |
| `mcp_tools_list` | A client requests the tool catalog (`tools/list`)       | Discovery measurement — are new clients finding the server  |
| `mcp_tool_call`  | A tool is invoked on the server (`tools/call` JSON-RPC) | Session detail, tool quality, intent clustering, dashboards |

Every event carries the `$mcp_*` property namespace plus a standard `$session_id`.
`$ai_product = 'mcp'` is set on all events so they can be filtered alongside the rest of AI observability.

## The session-grouping ids

There are three ids in play. Pick deliberately.

- **`$mcp_conversation_id`** — **the stable grouping key.** Survives transport reconnects, process restarts, and framework boundaries. Populated by the SDK when the calling agent echoes a conversation id (`@posthog/mcp-analytics` with `enableConversationId: true`). **Use this whenever you need a session that holds together across reconnects** — long-running coding sessions, multi-step agent workflows, anything where `$mcp_session_id` would split a single user intent into multiple rows.
- **`$mcp_session_id`** — transport-level session handle the MCP SDK observed for this request (e.g. MCP `extra.sessionId` or a framework session cookie). **Rotates per process restart, reconnect, or framework boundary** — fine for short-lived connections, wrong for anything that needs to span reconnects. This is what the Sessions tab and `posthog_mcp_session` table currently group by; expect that to migrate to `$mcp_conversation_id` over time.
- **`$session_id`** — the standard PostHog session id (`uuid7`). Kept for Session Replay compatibility. Do not use it to group MCP tool calls.

## Key `$mcp_*` properties

Pulled from `services/mcp/src/lib/posthog/analytics.ts:buildEventProperties` — that's the source of truth, check it if a property looks wrong.

**Per tool call**

- `$mcp_tool_name` — the tool the client invoked (e.g. `query_run`, `insight_get`)
- `$mcp_tool_description` — the description the agent saw at call time (descriptions change over time, this is what the agent acted on)
- `$mcp_intent` — natural-language description of why the agent called this tool. From a client-supplied context argument, or from a server-side `intentFallback`
- `$mcp_intent_source` — `'context_parameter'` (client supplied) or `'inferred'` (server fallback). Filter by this when judging intent quality
- `$mcp_is_error` — boolean; true if the tool call returned an error
- `$mcp_error_message` — error string when `$mcp_is_error` is true
- `$mcp_duration_ms` — server-side wall-clock latency
- `$mcp_exec_tool_call_name` / `$mcp_exec_tool_call_description` — only set in `cli` mode (single-exec), where every `$mcp_tool_name` is `exec` and the real inner tool lives here (server-side parses the `call <tool> ...` form)

**Per session / connection**

- `$mcp_conversation_id`, `$mcp_session_id` — see "session-grouping ids" above
- `$mcp_client_name`, `$mcp_client_version`, `$mcp_client_user_agent` — the MCP client (Claude Code, Codex, Claude Desktop, Claude on web, …)
- `$mcp_protocol_version` — MCP protocol revision (e.g. `2025-03-26`)
- `$mcp_transport` — `streamable_http`, `stdio`, etc.
- `$mcp_consumer` — upstream surface set by the `x-posthog-mcp-consumer` header. `'posthog-code'` for PostHog Code, `'slack'` for Slack-triggered
- `$mcp_mode` — tool-registration mode. **`'cli'` is single-exec mode** (v2 wrapper exposes one `exec` dispatcher); **`'tools'`** registers every tool individually
- `$mcp_oauth_client_name`, `$mcp_read_only`, `$mcp_region`

**Per server identity**

- `$mcp_server_name`, `$mcp_server_version` — advertised server identity
- `$mcp_source` — constant SDK identifier; lets you separate events from different SDK versions or unrelated MCP servers
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
- **Don't group by `distinct_id` to find sessions.** A single user can have many MCP sessions concurrently. Use `$mcp_conversation_id` for stable cross-reconnect grouping, or `$mcp_session_id` for raw transport-level sessions.
- **Person properties are point-in-time on events** (person-on-events mode is enabled). If you need the user's current name/email, resolve via the personhog client — never query `posthog_person` directly. See `posthog/personhog_client/README.md`.
- **The `MCPSession` row may not exist immediately.** It's populated by a Temporal workflow that runs periodically. For local dev, run `python manage.py seed_mcp_sessions --team-id <id>` to get fixture data without waiting.
- **`cli` mode flattens tool names.** When `$mcp_mode = 'cli'`, every `$mcp_tool_name` is `exec` (the dispatcher). The real inner tool is in `$mcp_exec_tool_call_name`. Always check `$mcp_mode` before aggregating by tool name in mixed populations — or pivot on `coalesce(properties.$mcp_exec_tool_call_name, properties.$mcp_tool_name)` to get the right answer regardless.

## Where to look in the code

- Event property emission: `services/mcp/src/lib/posthog/analytics.ts`
- Session list / tool-call queries: `products/mcp_analytics/backend/logic.py`
- Session backfill (events → `MCPSession`): `products/mcp_analytics/backend/backfill_sessions/`
- Intent summarisation: `products/mcp_analytics/backend/summarize_session_intents/`
- Intent clustering: `products/mcp_analytics/backend/intent_clustering.py`
- Default dashboard insights: `products/mcp_analytics/backend/dashboard_templates.py`
- Local seeding: `products/mcp_analytics/backend/management/commands/seed_mcp_sessions.py`
