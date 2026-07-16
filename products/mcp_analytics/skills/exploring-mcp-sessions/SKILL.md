---
name: exploring-mcp-sessions
description: >
  Investigate individual PostHog MCP sessions — the sequence of tool calls a
  single agent made in one run, what it was trying to do, and where it went
  wrong. Use when the user asks "what did this MCP session do?", "show me the
  tool calls for session X", "what was the agent's goal?", "which sessions had
  errors?", "who is connecting to my MCP?", or pastes an MCP analytics sessions
  URL.
---

# Exploring MCP sessions

An MCP session is one agent run: the set of `$mcp_tool_call` events sharing a
`$session_id`, ordered by `timestamp`.

Listing sessions, reading a session's tool calls, and summarising its goal each
have a **typed tool** — reach for those first. Drop to HogQL only for the three
things the typed tools genuinely can't do (see
[When to drop to SQL](#when-to-drop-to-sql)). The full `$mcp_*` property schema
and query recipes live in the shared reference:
[`models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).

## Tools

| Tool                                             | Purpose                                                    |
| ------------------------------------------------ | ---------------------------------------------------------- |
| `posthog:mcp-analytics-sessions-list`            | List sessions — one row per session, newest first          |
| `posthog:mcp-analytics-sessions-tool-calls`      | One session's tool calls, chronological                    |
| `posthog:mcp-analytics-sessions-generate-intent` | LLM summary of a session's goal (cached after first call)  |
| `posthog:execute-sql`                            | Errored sessions, effective tool names, cross-session cuts |

The three `mcp-analytics-*` tools are gated behind the `mcp-analytics` flag and
run the same code as the sessions UI, so results match the screen. A tool missing
from your list means one of two different things — don't collapse them into "no
flag":

- **All three absent** — the project likely doesn't have the `mcp-analytics`
  flag. Fall back to `posthog:execute-sql`, which is ungated, for the whole
  workflow.
- **Only `mcp-analytics-sessions-generate-intent` absent** while
  `sessions-list` and `sessions-tool-calls` are present — the flag _is_ on, but
  your token lacks the `mcp_analytics:write` scope that intent generation
  requires (the two list/detail tools only need `mcp_analytics:read`).
  Re-authenticate or request a connector / API key with `mcp_analytics:write`.
  SQL can still cover read-only list and detail work, but it **cannot** produce
  the LLM session summary — that has no ungated equivalent, so the write scope is
  the only way to get it.

## The date-window trap — read this first

The two detail tools default to a **7-day lookback**. A session you found in a
list that reaches further back will come back **empty** unless you pass its
`session_start` as `date_from`:

- `posthog:mcp-analytics-sessions-tool-calls` — `date_from` is an absolute ISO
  timestamp; pass the `session_start` you got from
  `posthog:mcp-analytics-sessions-list`.
- `posthog:mcp-analytics-sessions-generate-intent` — same `date_from` query
  param, same reason.

Empty tool calls for a session that visibly exists is almost always this, not a
data problem. Carry `session_start` forward from the list row.

## Workflow: list recent sessions

```json
posthog:mcp-analytics-sessions-list
{ "date_from": "-7d", "order_by": "-session_start", "limit": 100 }
```

Each row: `session_id`, `tool_calls`, `session_start`, `session_end`,
`tools_used`, `mcp_client_name`, `distinct_id` (+ resolved `person_email` /
`person_name`), and `intent` (empty until generated). Response is
`{ results, has_next }` — page with `limit` / `offset`.

Three sharp edges:

- **`order_by` takes column names, not response field names.** Sort call volume
  as `tool_call_count` (not `tool_calls`). `duration_seconds` sorts fine even
  though it isn't returned. An unrecognised key **silently** falls back to
  newest-first — so verify the order you got is the order you asked for. Valid:
  `session_id`, `session_start`, `session_end`, `duration_seconds`,
  `tool_call_count`, `mcp_client_name`, `distinct_id`; prefix `-` to descend.
- **There is no error filter and no error count on a session row.** "Which
  sessions had errors?" is a SQL question — see below.
- **`distinct_id_count` is always `0`.** The field is in the response but the
  backend never populates it, so don't read it as "one distinct id per session"
  — it says nothing. To count distinct ids in a session, use SQL.

`search` does a case-insensitive substring match across `session_id`,
`distinct_id`, `mcp_client_name`, and `tools_used`.

## Workflow: read one session's tool calls

```json
posthog:mcp-analytics-sessions-tool-calls
{ "id": "<session_id>", "date_from": "<session_start>", "limit": 500 }
```

Chronological `tool_name`, `intent`, `timestamp`, `duration_ms`, `is_error`,
`error_message` — read top to bottom to reconstruct the run. `limit` defaults to
500 (also the max), which is the whole page for almost every session; `has_next`
tells you if more remain.

**Caveat: `tool_name` here is the raw `$mcp_tool_name`.** Unlike the tool-quality
and tool-detail tools, this endpoint does not resolve the inner tool of a
single-exec wrapper call, so wrapper calls show the wrapper. When the inner tool
is what matters (comparing against a tool-quality ranking, tracing a specific
tool through a run), use the SQL recipe below instead. The same applies to
`tools_used` on the session list.

## Workflow: summarise the agent's goal

```json
posthog:mcp-analytics-sessions-generate-intent
{ "id": "<session_id>", "date_from": "<session_start>" }
```

Summarises the session's recorded `$mcp_intent` values via an LLM and persists
the result; later calls return the cached summary. Returns
`{ session_id, intent }`. A 503 means LLM summarisation isn't configured — fall
back to reading the raw `$mcp_intent` values from the tool-call list.

## When to drop to SQL

Four cases, all via `posthog:execute-sql`, which — unlike the typed tools above —
is **not** gated behind the `mcp-analytics` flag.

**1. The project doesn't have the `mcp-analytics` flag** (all three typed tools
absent). Everything below still works; this query is the plain session listing.
Note SQL is a read-only substitute — it can list, detail, and aggregate, but it
cannot generate the LLM intent summary. If only
`mcp-analytics-sessions-generate-intent` is missing, the flag is on and you're
short the `mcp_analytics:write` scope, not the flag — get the scope rather than
falling back here for intent.

```sql
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

**2. Errored sessions.** The session list can't filter or count errors — add
`HAVING errors > 0` to the query above and order by `errors DESC`.

**3. Effective tool names within a session** — the coalesce the typed tool-calls
endpoint doesn't apply:

```sql
SELECT
    timestamp,
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    toBool(properties.$mcp_is_error) AS is_error,
    toString(properties.$mcp_error_message) AS error_message,
    round(toFloat(properties.$mcp_duration_ms)) AS duration_ms
FROM events
WHERE event = '$mcp_tool_call'
    AND $session_id = '<session_id>'
ORDER BY timestamp ASC
```

**4. Cross-session aggregation** — "sessions per day", "sessions that used tool
X and then failed", custom breakdowns. Recipes in
[`models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).

Note `$session_id` is a **materialised events column** — the same id as
`$mcp_session_id`. Reference it bare, never as `properties.$session_id`: the
`properties.` accessor renders null-wrapped in SELECT but as the raw column in
HAVING/ORDER, so a `HAVING` search would mismatch the `GROUP BY` key.

## Constructing UI links

- **Sessions list**: `https://app.posthog.com/project/<project_id>/mcp-analytics/sessions`

## Tips

- A session with many calls but no errors that ends abruptly often means the
  agent gave up — check whether the last call returned a large or empty result
- `$mcp_intent` is only present when the client supplied it; absence is common,
  so generate-intent is the more reliable goal signal
- To go from a failing tool (see
  [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md)) to the
  sessions that hit it, `search` the session list by tool name — remembering
  `tools_used` holds raw names, so search the registered name, not the inner one

## Related skills

- [`exploring-mcp-tool-usage`](../exploring-mcp-tool-usage/SKILL.md) — the front
  door: routes a broad "how is my MCP doing?" question to the right tool
- [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md) — error
  rates and latency across all tools
- [`exploring-mcp-intent-clusters`](../exploring-mcp-intent-clusters/SKILL.md) —
  group goals across many sessions
