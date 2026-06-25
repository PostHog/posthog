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
share a `$session_id`, ordered by `timestamp`. Listing sessions and reading
a session's tool calls are both plain HogQL over `events`; the full property
schema and recipes are in the shared reference:
[`products/posthog_ai/skills/querying-posthog-data/references/models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).

The one thing SQL cannot do is summarise the agent's _goal_ in prose — that is
the typed tool `posthog:mcp-analytics-sessions-generate-intent`.

## Tools

| Tool                                             | Purpose                                                       |
| ------------------------------------------------ | ------------------------------------------------------------- |
| `posthog:execute-sql`                            | List sessions and read a session's tool-call sequence (HogQL) |
| `posthog:mcp-analytics-sessions-generate-intent` | Generate (or fetch cached) LLM summary of a session's goal    |

## Workflow: list recent sessions

Group `$mcp_tool_call` by `$session_id`, deriving start/end, duration, call
count, error count, and the harness:

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
ORDER BY session_start DESC
LIMIT 50
```

Add `HAVING errors > 0` to surface only sessions that hit failures.

## Workflow: read one session's tool calls

The chronological sequence of what the agent did — the heart of debugging a run:

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

Always use the effective-tool-name `coalesce(...)` so single-exec wrapper calls
resolve to the real tool. Read these top to bottom to reconstruct the run.

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
  sessions that hit it, filter the sessions query on the effective tool name

## Related skills

- [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md) — error
  rates and latency across all tools
- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) —
  group goals across many sessions
