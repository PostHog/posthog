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
`mcp_tool_call` event on the shared `events` table every time an agent invokes a
tool. There is **no dedicated ClickHouse table** — every field lives as a
`$mcp_*` property on `events`, and every tool-quality metric (error rate, latency
percentiles, reach) is an aggregation over this one event. This is the data
behind the MCP analytics dashboard and tool-quality screens.

**HogQL via `posthog:execute-sql` is the primary path.** There are no typed
tools for tool quality — it is all SQL. The full property schema and the
canonical query recipes live in the shared MCP data reference:
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

- **Always count errors with both signals.** Newer events set `$mcp_is_error`; older
  events carry only an unprefixed `success` boolean. Reading `$mcp_is_error` alone
  undercounts errors (every legacy call is treated as a success) while keeping them in the
  denominator. Use:

  ```sql
  coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))
  ```

  Cast `$mcp_duration_ms` via `toFloat(...)`. The properties are strings.

Always set a time range — these queries scan `events` otherwise.

## Workflow: which tool has the highest error rate

This is the canonical "which tool errors most" question. Rank tools by error
rate, but guard against small-sample noise with a `HAVING` floor on call volume:

```sql
posthog:execute-sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS total_calls,
    countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) AS errors,
    round(countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) * 100.0 / count(), 1) AS error_rate_pct
FROM events
WHERE event = 'mcp_tool_call'
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

Pull the most common error messages for a tool, then correlate to richer
exception detail (`$exception` events carry `$exception_message`, joined by
`$mcp_session_id` / `$session_id` and timestamp):

```sql
posthog:execute-sql
SELECT toString(properties.$mcp_error_message) AS error, count() AS n
FROM events
WHERE event = 'mcp_tool_call'
    AND coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY error ORDER BY n DESC LIMIT 10
```

## Workflow: slowest tools

Swap the aggregate for latency percentiles
(`quantile(0.95)(toFloat(properties.$mcp_duration_ms))`) and order by `p95_ms`.
The matrix query already returns `p50_ms` / `p95_ms`.

## Constructing UI links

Use the project's region-aware host, not a hardcoded `app.posthog.com` — derive it from the
`generate-app-url` tool (or the Base URL in the active environment, e.g. `us.posthog.com` /
`eu.posthog.com`):

- **Dashboard**: `<base_url>/project/<project_id>/mcp-analytics/dashboard`
- **Tool quality**: `<base_url>/project/<project_id>/mcp-analytics/tool-quality`

Always surface a UI link so the user can verify visually.

## Tips

- Report error rate **and** call volume together; a `HAVING total_calls >= N`
  floor stops tools with very few calls from topping the list spuriously
- Exclude errored calls from latency percentiles only when asked — failed calls
  are often the slow ones, and dropping them hides the problem
- `mcp_session_client_name` lets you cut quality by harness (Claude Code vs Cursor
  vs …); the canonical bucketing `multiIf` is in
  [models-mcp.md](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).
  (The older `$mcp_client_name` is effectively unset on current data — don't filter on it.)
- If the SQL contradicts the tool-quality screen, trust the screen and flag this
  skill for an update — the frontend bucketing logic is the source of truth

## Related skills

- [`exploring-mcp-sessions`](../exploring-mcp-sessions/SKILL.md) — drill into a
  single agent run and its tool sequence
- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) —
  group agent goals and see which intents drive the errors
