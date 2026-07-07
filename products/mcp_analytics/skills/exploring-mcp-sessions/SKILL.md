---
name: exploring-mcp-sessions
description: >
  Investigate individual PostHog MCP sessions — the sequence of tool calls a
  single agent made in one run, what it was trying to do, and where it went
  wrong. Use when the user asks "what did this MCP session do?", "show me the
  tool calls for session X", "what was the agent's goal?", "which sessions had
  errors?", or pastes an MCP analytics sessions URL.
---

# Exploring MCP sessions

An MCP session is one agent run, identified by `$session_id` on the
`$mcp_tool_call` event. A session is just the set of `$mcp_tool_call` events that
share a `$session_id`, ordered by `timestamp`.

**Prefer the typed, read-only tools for the two core workflows** —
`posthog:mcp-analytics-sessions-list` to list sessions and
`posthog:mcp-analytics-sessions-tool-calls` to read one session's tool-call
sequence. Both run the same query runner as the sessions UI, resolve
`person_email` / `person_name`, apply the effective-tool-name and empty-session
guards for you, and are gated behind the `mcp-analytics` flag — no hand-written
SQL needed. Drop to `posthog:execute-sql` only for custom aggregation the typed
tools do not expose; the full property schema and query recipes live in the
shared reference:
[`products/posthog_ai/skills/querying-posthog-data/references/models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).

The one thing SQL cannot do is summarise the agent's _goal_ in prose — that is
the typed tool `posthog:mcp-analytics-sessions-generate-intent`.

## Tools

| Tool                                             | Purpose                                                          |
| ------------------------------------------------ | --------------------------------------------------------------- |
| `posthog:mcp-analytics-sessions-list`            | List recent sessions (readOnly) — one row per session           |
| `posthog:mcp-analytics-sessions-tool-calls`      | Read one session's chronological tool calls (readOnly)          |
| `posthog:mcp-analytics-sessions-generate-intent` | Generate (or fetch cached) LLM summary of a session's goal      |
| `posthog:execute-sql`                            | Escape hatch — custom aggregation not covered by the tools above |

## Workflow: list recent sessions

Call the typed tool — one row per session, newest first, with `session_id`,
`tool_calls`, `session_start`/`session_end`, `tools_used`, `mcp_client_name`, and
the resolved `person_email` / `person_name`:

```json
posthog:mcp-analytics-sessions-list
{ "limit": 50 }
```

- Sort with `order_by` (its keys are the underlying column names: use
  `tool_call_count` for `tool_calls`, `duration_seconds` for session length; an
  unrecognised key falls back to newest-first).
- Narrow with a case-insensitive `search`, a `date_from`/`date_to` window
  (default last 7 days), and page with `limit`/`offset`.

**Escape hatch** — only for custom aggregation the tool does not expose (e.g. a
custom `HAVING errors > 0` filter), group `$mcp_tool_call` by `$session_id`:

```sql
posthog:execute-sql
SELECT
    $session_id AS session_id,
    min(timestamp) AS session_start,
    max(timestamp) AS session_end,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    any(properties.$mcp_client_name) AS client
FROM events
WHERE event = '$mcp_tool_call'
    AND $session_id != ''
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY session_id
HAVING errors > 0
ORDER BY session_start DESC
LIMIT 50
```

## Workflow: read one session's tool calls

The chronological sequence of what the agent did — the heart of debugging a run.
Call the typed tool with the session's `session_id`; each call returns
`tool_name`, `intent`, `timestamp`, `duration_ms`, and `is_error` /
`error_message`:

```json
posthog:mcp-analytics-sessions-tool-calls
{ "id": "<session_id>" }
```

For sessions older than the default 7-day lookback, also pass the session's
`session_start` as `date_from` so the event scan reaches them. The response's
`has_next` flag indicates whether more calls remain (page with `limit`/`offset`,
default page size 500).

**Escape hatch** — only when you need fields or filters the tool does not
expose. Always use the effective-tool-name `coalesce(...)` so single-exec wrapper
calls resolve to the real tool:

```sql
posthog:execute-sql
SELECT
    timestamp,
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    toBool(properties.$mcp_is_error) AS is_error,
    toString(properties.$mcp_error_message) AS error_message,
    round(toFloat(properties.$mcp_duration_ms)) AS duration_ms,
    toString(properties.$mcp_intent) AS intent
FROM events
WHERE event = '$mcp_tool_call'
    AND $session_id = '<session_id>'
ORDER BY timestamp ASC
```

## Workflow: summarise the agent's goal

When the user wants the _intent_ of a session in prose (not the raw tool list),
call the typed tool — the first call summarises the recorded `$mcp_intent`
values via an LLM and persists the result; later calls return the cached summary:

```json
posthog:mcp-analytics-sessions-generate-intent
{ "id": "<session_id>" }
```

Returns `{ "session_id": ..., "intent": "<prose summary>" }`. If it returns 503,
LLM summarisation is unavailable — fall back to reading the raw `$mcp_intent`
values from the tool-call query above.

## Constructing UI links

- **Sessions list**: `https://app.posthog.com/project/<project_id>/mcp-analytics/sessions`

## Tips

- A session with many calls but no errors that ends abruptly often means the
  agent gave up — check whether the last call returned a large/empty result
- `$mcp_intent` is only present when the client supplied it; absence is common,
  so the generate-intent tool is the more reliable goal signal
- To go from a failing tool (see
  [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md)) to the
  sessions that hit it, pass the tool name as `search` to
  `posthog:mcp-analytics-sessions-list` (or filter the escape-hatch query on the
  effective tool name)

## Related skills

- [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md) — error
  rates and latency across all tools
- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) —
  group goals across many sessions
