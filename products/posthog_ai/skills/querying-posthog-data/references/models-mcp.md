# MCP analytics (`mcp_tool_call` events)

PostHog's own MCP server emits a `mcp_tool_call` event on the shared `events` table every time an agent invokes a tool. There is **no dedicated ClickHouse table** — all fields live as `$mcp_*` properties on `events`, queried directly with `posthog:execute-sql`. This is the data behind the MCP analytics dashboard, tool-quality, and tool-detail screens; every metric on those screens is reproducible as HogQL over this event.

**HogQL is the primary path here.** Session listing, per-session tool calls, tool-level metrics (error rate, latency, adoption), harness breakdowns, time series, and co-occurrence are all just aggregations over this event — query them with `execute-sql`. The only typed tools are for things SQL can't express: `posthog:mcp-analytics-intent-clusters-retrieve` / `...-recompute` (embedding-based intent clustering) and `posthog:mcp-analytics-sessions-generate-intent` (LLM session summary).

## Key properties

| Property                   | Meaning                                                                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_tool_name`           | Registered tool name.                                                                                                                    |
| `$mcp_exec_tool_call_name` | Inner tool name when the call went through the new-SDK single-exec wrapper. See effective-tool-name note below.                          |
| `$mcp_is_error`            | Whether the call failed (newer events). Read via `toBool(...)`, but see the error-signal note — older events use `success` instead.      |
| `success`                  | Legacy unprefixed error signal: `true` = ok, `false` = failed. Present on calls that predate `$mcp_is_error`; the two are mutually exclusive. |
| `$mcp_error_message`       | Error text when the call failed.                                                                                                         |
| `$mcp_duration_ms`         | Wall-clock duration; cast with `toFloat(...)`.                                                                                           |
| `$mcp_session_id`          | Session/conversation id — the grouping key for a single agent run.                                                                       |
| `$mcp_intent`              | The agent's stated intent for the call, when supplied. Often absent — test presence with `isNotNull(...)` / `JSONHas(...)`, never `toString(...) != ''`. |
| `mcp_session_client_name`  | Raw client string (e.g. `claude-code/1.2.3`). The dashboard buckets these into harnesses in the frontend; there is no `category` column. (The older `$mcp_client_name` is effectively unset on current data — coalesce them for legacy coverage.) |
| `$mcp_tool_category`       | Tool category, when tagged.                                                                                                              |
| `$mcp_tool_description`    | Tool description as seen by the agent (revisions over time).                                                                             |

**Effective tool name.** New-SDK events wrap the real tool in a single-exec call, so to filter/group by the tool the agent actually invoked, use:

```sql
coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))
```

**Error signal.** Newer events set `$mcp_is_error`; older events carry only an unprefixed `success` boolean (the two are mutually exclusive — every call has exactly one). Counting `toBool(properties.$mcp_is_error)` alone silently treats every legacy `success`-only call as a non-error while still keeping it in the denominator, deflating error rates. Use the coalescing expression so both generations count:

```sql
coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))
```

**Testing property presence.** A missing JSON key renders under `toString(...)` as the non-empty literal `'None'`, so `toString(properties.$mcp_intent) != ''` is **always true** — it reports 100% coverage even when the property is set on zero rows. Use `isNotNull(properties.$mcp_intent)` or `JSONHas(properties, '$mcp_intent')` to test presence, and `isNotNull(...)` (not `toString(...) != ''`) when filtering rows down to a present key such as `$mcp_session_id`.

**Failures with detail.** `mcp_tool_call` carries the error signal above + `$mcp_error_message`; richer stack/exception data is on `$exception` events (`$exception_message`), correlated by `$mcp_session_id` / `$session_id` and timestamp.

## Example queries

**Error rate of one tool:**

```sql
SELECT
    count() AS total_calls,
    countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) AS errors,
    round(countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) * 100.0 / count(), 1) AS error_rate_pct
FROM events
WHERE event = 'mcp_tool_call'
    -- effective tool name: new-SDK events put the real tool in $mcp_exec_tool_call_name
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool-name>'
    AND timestamp >= now() - INTERVAL 7 DAY
```

**Tool-quality matrix** (error rate + latency percentiles + reach, one row per tool):

```sql
SELECT
    -- effective tool name: new-SDK events put the real tool in $mcp_exec_tool_call_name,
    -- so grouping on raw $mcp_tool_name would collapse them under the single-exec wrapper
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS total_calls,
    round(countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50_ms,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_ms,
    uniq(distinct_id) AS users,
    countDistinctIf(toString(properties.$mcp_session_id), isNotNull(properties.$mcp_session_id)) AS sessions
FROM events
WHERE event = 'mcp_tool_call'
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) != ''
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY tool
ORDER BY total_calls DESC
```

**Daily activity** (success/error split for a time series):

```sql
SELECT toDate(timestamp) AS day,
    countIf(NOT coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) AS successes,
    countIf(coalesce(toBool(properties.$mcp_is_error), NOT toBool(properties.success))) AS errors
FROM events
WHERE event = 'mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day ORDER BY day
```

### Harness (client) bucketing

`mcp_session_client_name` is the raw client string the MCP client sends (`claude-code/1.2.3`, `Anthropic/ClaudeAI`, `windsurf`, sometimes with a `(via mcp-remote …)` suffix). (The older `$mcp_client_name` is set on a negligible fraction of current data — coalesce the two so legacy events still bucket.) A bare `GROUP BY properties.mcp_session_client_name` fragments a single harness across version/variant strings. To group by harness, normalize the raw client name in an inner subquery, then bucket it with `multiIf`. This mapping mirrors `HARNESS_CATEGORIES` / `categorizeHarness()` in `products/mcp_analytics/frontend/mcpDashboardOverviewLogic.ts` — keep the two in sync until a materialized `$mcp_harness` property exists. (HogQL has no `WITH <expr> AS alias`, so the normalized name `h` is computed in a subquery, not a CTE.)

**Share of users by harness** (answers "what % of my users are on Claude Code"):

```sql
SELECT
    harness,
    uniq(distinct_id) AS users,
    round(uniq(distinct_id) * 100.0 / (
        SELECT uniq(distinct_id) FROM events
        WHERE event = 'mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
    ), 1) AS pct_of_users
FROM (
    SELECT
        distinct_id,
        multiIf(
            startsWith(h, 'claude-code'), 'Claude Code',
            h IN ('claude-ai', 'anthropic/claudeai'), 'Claude.ai',
            h = 'anthropic/api', 'Anthropic API',
            startsWith(h, 'codex') OR startsWith(h, 'openai-mcp'), 'OpenAI Codex',
            startsWith(h, 'cursor'), 'Cursor',
            startsWith(h, 'visual studio code'), 'VS Code',
            h = 'windsurf', 'Windsurf',
            startsWith(h, 'replit'), 'Replit',
            startsWith(h, 'lovable'), 'Lovable',
            h = 'manus', 'Manus',
            h = 'coderabbit', 'CodeRabbit',
            startsWith(h, 'notion'), 'Notion',
            h = 'poke', 'Poke',
            h = 'opencode', 'opencode',
            startsWith(h, 'kiro'), 'Kiro',
            startsWith(h, 'desktop-commander'), 'Desktop Commander',
            'Other'
        ) AS harness
    FROM (
        SELECT
            distinct_id,
            lower(trim(replaceRegexpOne(coalesce(nullIf(toString(properties.mcp_session_client_name), ''), toString(properties.$mcp_client_name)), '\\s*\\(via mcp-remote[^)]*\\)\\s*', ''))) AS h
        FROM events
        WHERE event = 'mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
    )
)
GROUP BY harness
ORDER BY users DESC
```

The `multiIf` above is the canonical bucket list. The denominator is total distinct users, so per-harness shares can sum past 100% (one user may use several harnesses). Swap the outer aggregate for other harness cuts — `count()` for call volume, `quantile(0.95)(toFloat(properties.$mcp_duration_ms))` for latency. For `query-trends`, pass the inner `multiIf(...)` over the normalized client name as a **HogQL breakdown** to get the same buckets in a trends series.

**Tool co-occurrence** (which tool tends to run right before a given tool, within a session):

```sql
SELECT prev_tool AS tool, count() AS co_occurrences
FROM (
    SELECT properties.$mcp_session_id AS conv_id,
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        lagInFrame(coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)))
            OVER (PARTITION BY properties.$mcp_session_id ORDER BY timestamp
                  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_tool
    FROM events
    WHERE event = 'mcp_tool_call' AND timestamp >= now() - INTERVAL 7 DAY
)
WHERE tool = '<tool-name>' AND prev_tool != '' AND prev_tool != tool
GROUP BY prev_tool ORDER BY co_occurrences DESC LIMIT 5
```

Swap `lagInFrame` for `leadInFrame` to get the tool that runs _after_.
