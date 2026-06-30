---
name: exploring-mcp-tool-quality
description: >
  Investigate the quality of PostHog MCP tool calls — error rates, latency,
  reach, and which tools are failing or slow. Use when the user asks "which
  MCP tool has the highest error rate?", "what's the slowest tool?", "which
  tools fail most often?", "how reliable is tool X?", wants a tool-quality
  matrix, or pastes an MCP analytics tool-quality / dashboard URL and asks
  what it shows.
---

# Exploring MCP tool quality

Any MCP server instrumented with PostHog's MCP analytics SDK emits a
`$mcp_tool_call` event on the shared `events` table every time an agent invokes a
tool. There is **no dedicated ClickHouse table** — every field lives as a
`$mcp_*` property on `events`, and every tool-quality metric (error rate, latency
percentiles, reach) is an aggregation over this one event. This is the data
behind the MCP analytics dashboard and tool-quality screens.

**For a single tool, prefer the typed tools** — `posthog:query-mcp-tool-stats` (calls,
errors, p50/p95, users, sessions, intents), `posthog:query-mcp-tool-failures` (top error
messages by harness), and `posthog:query-mcp-tool-daily-stats` (day-by-day trend). Each
takes a `toolName` + `dateRange`, runs the same query runner as the tool-detail
UI, and is gated behind the `mcp-analytics` flag — no hand-written SQL needed.

**HogQL via `posthog:execute-sql` is the path for cross-tool questions** — the
"which tool errors most" ranking below has no typed tool, so rank with SQL, then
drill into the worst tool with `posthog:query-mcp-tool-stats` / `-failures`. The full
property schema and the canonical query recipes live in the shared MCP data
reference:
[`products/posthog_ai/skills/querying-posthog-data/references/models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).
That reference is the single source of truth for the `$mcp_*` schema and the
effective-tool-name idiom used below — this skill inlines only the headline
"which tool errors most" query for convenience; pull the matrix, latency, and
harness recipes from the reference rather than re-deriving them. Read it before
writing queries.

## The two rules that matter most

- **Always use the effective tool name.** New-SDK events wrap the real tool in
  a single-exec call, so grouping on raw `$mcp_tool_name` collapses everything
  under the wrapper. Use:

  ```sql
  coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))
  ```

- **Always read `$mcp_is_error` via `toBool(...)`** and cast
  `$mcp_duration_ms` via `toFloat(...)`. The properties are strings.

Always set a time range — these queries scan `events` otherwise.

## Workflow: which tool has the highest error rate

This is the canonical "which tool errors most" question. Rank tools by error
rate, but guard against small-sample noise with a `HAVING` floor on call volume:

```sql
posthog:execute-sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct
FROM events
WHERE event = '$mcp_tool_call'
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) != ''
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY tool
HAVING total_calls >= 20
ORDER BY error_rate_pct DESC, total_calls DESC
LIMIT 20
```

Report both **rate and volume** — a 100% error rate over 3 calls is rarely the
real story; a 12% rate over 50,000 calls is. Offer to pull the top
`$mcp_error_message` values for the worst tool (see below).

## Workflow: tool-quality matrix

One row per tool with error rate, latency percentiles, and reach — mirrors the
tool-quality screen. The ready-to-run query is in
[models-mcp.md](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md)
under "Tool-quality matrix".

## Workflow: why is a tool failing

For one tool's top error messages (grouped by harness), call
`posthog:query-mcp-tool-failures` with the `toolName` — it's the typed equivalent of the
query below. Pass the **raw** `$mcp_tool_name` (the registered tool name), not
the effective inner tool: failures match `$exception` events, which don't carry
the new-SDK effective-tool markers. Drop to SQL only to correlate to richer
exception detail (`$exception` events carry `$exception_message`, joined by
`$session_id` and timestamp) — that session join is approximate: it surfaces
every exception in the session, not only this tool's, so treat it as a lead, not
exact attribution:

```sql
posthog:execute-sql
SELECT toString(properties.$mcp_error_message) AS error, count() AS n
FROM events
WHERE event = '$mcp_tool_call'
    AND toBool(properties.$mcp_is_error)
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY error ORDER BY n DESC LIMIT 10
```

## Workflow: slowest tools

Swap the aggregate for latency percentiles
(`quantile(0.95)(toFloat(properties.$mcp_duration_ms))`) and order by `p95_ms`.
The matrix query already returns `p50_ms` / `p95_ms`.

## Constructing UI links

- **Dashboard**: `https://app.posthog.com/project/<project_id>/mcp-analytics/dashboard`
- **Tool quality**: `https://app.posthog.com/project/<project_id>/mcp-analytics/tool-quality`

Always surface a UI link so the user can verify visually.

## Tips

- Report error rate **and** call volume together; a `HAVING total_calls >= N`
  floor stops tools with very few calls from topping the list spuriously
- Exclude errored calls from latency percentiles only when asked — failed calls
  are often the slow ones, and dropping them hides the problem
- `$mcp_client_name` lets you cut quality by harness (Claude Code vs Cursor vs
  …); the canonical bucketing `multiIf` is in
  [models-mcp.md](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md)
- If the SQL contradicts the tool-quality screen, trust the screen and flag this
  skill for an update — the frontend bucketing logic is the source of truth

## Related skills

- [`exploring-mcp-sessions`](../exploring-mcp-sessions/SKILL.md) — drill into a
  single agent run and its tool sequence
- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) —
  group agent goals and see which intents drive the errors
