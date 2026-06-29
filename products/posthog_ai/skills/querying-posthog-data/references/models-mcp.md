# MCP analytics (`$mcp_tool_call` events)

Any MCP server instrumented with the `@posthog/mcp` SDK — and PostHog's own MCP server — emits a `$mcp_tool_call` event on the shared `events` table every time an agent invokes a tool. There is **no dedicated ClickHouse table** — all fields live as `$mcp_*` properties on `events`, queried directly with `posthog:execute-sql`. This is the data behind the MCP analytics dashboard, tool-quality, and tool-detail screens; every metric on those screens is reproducible as HogQL over this event.

Query the canonical `$`-prefixed event name. Servers instrumented with the `@posthog/mcp` SDK emit only `$mcp_tool_call` / `$mcp_initialize`; PostHog's own hosted server additionally dual-emits legacy un-prefixed `mcp_tool_call` / `mcp_initialize` aliases through a transition shim. Match the canonical name only — an `event IN ('mcp_tool_call', '$mcp_tool_call')` would double-count PostHog's own server.

**For a single tool, prefer the typed tools.** Each takes a `toolName` plus a `dateRange`, runs the same query runner the tool-detail UI uses, and is gated behind the `mcp-analytics` flag, so results match the UI exactly and you don't re-derive the SQL below. For all of them **except `posthog:query-mcp-tool-failures`**, `toolName` is the effective name (resolved server-side — the inner tool of a single-exec wrapper call). `posthog:query-mcp-tool-failures` is the exception: it matches `$exception` events, which don't carry the new-SDK effective-tool markers, so it takes the **raw** `$mcp_tool_name` (the registered tool name):

| question about one tool                                             | tool                                                     |
| ------------------------------------------------------------------- | -------------------------------------------------------- |
| headline numbers (calls, errors, p50/p95, users, sessions, intents) | `posthog:query-mcp-tool-stats`                           |
| day-by-day trend                                                    | `posthog:query-mcp-tool-daily-stats`                     |
| top error messages, by harness                                      | `posthog:query-mcp-tool-failures` (raw `$mcp_tool_name`) |
| top callers (incl. person email/name)                               | `posthog:query-mcp-tool-top-users`                       |
| tools called before/after it (`neighborDirection: before`/`after`)  | `posthog:query-mcp-tool-neighbors`                       |
| recent agent intents                                                | `posthog:query-mcp-tool-sample-intents`                  |
| distinct descriptions seen                                          | `posthog:query-mcp-tool-descriptions`                    |

And `posthog:query-mcp-harness-breakdown` for the cross-tool harness cut (see below).

**HogQL is the path for everything else** — cross-tool rankings (the tool-quality matrix), custom breakdowns, session listing, per-session tool calls — query them with `execute-sql`. Two more typed tools cover what SQL can't express: `posthog:mcp-analytics-intent-clusters-retrieve` / `...-recompute` (embedding-based intent clustering) and `posthog:mcp-analytics-sessions-generate-intent` (LLM session summary).

## Key properties

| Property                   | Meaning                                                                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_tool_name`           | Registered tool name.                                                                                                                    |
| `$mcp_exec_tool_call_name` | Inner tool name when the call went through the new-SDK single-exec wrapper. See effective-tool-name note below.                          |
| `$mcp_is_error`            | Whether the call failed. Always read via `toBool(properties.$mcp_is_error)`.                                                             |
| `$mcp_error_message`       | Error text when `$mcp_is_error` is true.                                                                                                 |
| `$mcp_duration_ms`         | Wall-clock duration; cast with `toFloat(...)`.                                                                                           |
| `$session_id`              | Session/conversation id — the grouping key for a single agent run. Use the bare `$session_id` field, not `properties.$session_id`.       |
| `$mcp_intent`              | The agent's stated intent for the call, when supplied.                                                                                   |
| `$mcp_client_name`         | Raw client string (e.g. `claude-code/1.2.3`). The dashboard buckets these into harnesses in the frontend; there is no `category` column. |
| `$mcp_tool_category`       | Tool category, when tagged.                                                                                                              |
| `$mcp_tool_description`    | Tool description as seen by the agent (revisions over time).                                                                             |

**Effective tool name.** New-SDK events wrap the real tool in a single-exec call, so to filter/group by the tool the agent actually invoked, use:

```sql
coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))
```

**Failures with detail.** `$mcp_tool_call` carries `$mcp_is_error` + `$mcp_error_message`; richer stack/exception data is on `$exception` events (`$exception_message`), correlated by `$mcp_session_id` / `$session_id` and timestamp.

## Example queries

The SQL below is the fallback for cross-tool rankings and custom cuts. For a single tool's numbers, call the typed tool from the table above instead of re-deriving these.

**Error rate of one tool** (single-tool headline numbers are `posthog:query-mcp-tool-stats`; use this for a custom predicate):

```sql
SELECT
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct
FROM events
WHERE event = '$mcp_tool_call'
    -- effective tool name: new-SDK events put the real tool in $mcp_exec_tool_call_name
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool-name>'
    AND timestamp >= now() - INTERVAL 7 DAY
```

**Tool-quality matrix** (error rate + latency percentiles + reach, one row per tool) — this cross-tool ranking has no typed tool; once you've picked a tool, drill into it with `posthog:query-mcp-tool-stats` / `-failures` / `-daily-stats`:

```sql
SELECT
    -- effective tool name: new-SDK events put the real tool in $mcp_exec_tool_call_name,
    -- so grouping on raw $mcp_tool_name would collapse them under the single-exec wrapper
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS total_calls,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50_ms,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_ms,
    uniq(distinct_id) AS users,
    countDistinctIf($session_id, $session_id != '') AS sessions
FROM events
WHERE event = '$mcp_tool_call'
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) != ''
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY tool
ORDER BY total_calls DESC
```

**Daily activity** (success/error split for a time series) — for one tool's daily series prefer `posthog:query-mcp-tool-daily-stats`; this all-tools version is the custom cut:

```sql
SELECT toDate(timestamp) AS day,
    countIf(NOT toBool(properties.$mcp_is_error)) AS successes,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day ORDER BY day
```

### Harness (client) bucketing

A "harness" is the friendly product label for the MCP client that made a call — "Claude Agent SDK", "OpenAI Codex", "Cursor", … It is resolved **server-side** by `MCPHarnessBreakdownQueryRunner`, the single source of truth (`products/mcp_analytics/backend/mcp_harness.py`).

**Prefer the typed tool.** For "which harnesses use our MCP, and how reliably?", call the `posthog:query-mcp-harness-breakdown` tool (gated behind the `mcp-analytics` flag). It returns calls / errors / error-rate / sessions per harness and accepts the same `dateRange` / `properties` / `filterTestAccounts` filters as the dashboard, so results match the UI exactly — no hand-written bucketing needed. (The session/feedback REST tools — `mcp-analytics-sessions-list` etc. — are disabled, so anything the typed tool doesn't express drops to `execute-sql` below.)

**Use `execute-sql` for custom cuts** the typed tool doesn't cover (share-of-users, latency percentiles, per-tool, a trends breakdown). Resolution is two steps: resolve a normalized token from the strongest signal available, then bucket it. An event carries only raw signals — the `x-anthropic-client` header (`mcp_vendor_client`) is the only thing separating Anthropic's pooled surfaces (Cowork / Claude.ai / Claude Design); Claude Code's build (cli / sdk / vscode / desktop) rides in the User-Agent; the posthog-node MCP analytics SDK reports its `clientInfo.name` as `$mcp_client_name`, and the hosted server's session-pinned `mcp_session_client_name` covers everyone else; `$mcp_client_user_agent` and `$mcp_oauth_client_name` are last fallbacks. The SQL below mirrors `harness_label_sql` / `HARNESS_TOKEN_SQL` in `mcp_harness.py`; keep them in step until a materialized `$mcp_harness` property exists. (HogQL has no `WITH <expr> AS alias`, so the normalized name `h` is computed in a subquery, not a CTE.)

**Share of users by harness** (answers "what % of my users are on Claude Code"):

```sql
SELECT
    harness,
    uniq(distinct_id) AS users,
    round(uniq(distinct_id) * 100.0 / (
        SELECT uniq(distinct_id) FROM events
        WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
    ), 1) AS pct_of_users
FROM (
    SELECT
        distinct_id,
        multiIf(
            h = 'claude-code claude-desktop', 'Claude Desktop',
            h = 'claude-code claude-vscode', 'Claude Code (VS Code)',
            startsWith(h, 'claude-code sdk'), 'Claude Agent SDK',
            startsWith(h, 'claude-code'), 'Claude Code',
            h IN ('claude-ai', 'anthropic/claudeai', 'claude-user'), 'Claude.ai',
            h = 'anthropic/api', 'Anthropic API',
            h = 'cowork', 'Cowork',
            h = 'claude-design', 'Claude Design',
            h = 'openai-mcp chatgpt', 'ChatGPT',
            h = 'openai-mcp agent builder', 'OpenAI Agent Builder',
            h = 'openai-mcp responses api', 'OpenAI Responses API',
            startsWith(h, 'openai-mcp'), 'OpenAI',
            startsWith(h, 'codex'), 'OpenAI Codex',
            startsWith(h, 'cursor'), 'Cursor',
            startsWith(h, 'visual studio code'), 'VS Code',
            h = 'windsurf', 'Windsurf',
            startsWith(h, 'replit'), 'Replit',
            startsWith(h, 'lovable'), 'Lovable',
            h = 'manus', 'Manus',
            h = 'coderabbit', 'CodeRabbit',
            startsWith(h, 'notion'), 'Notion',
            startsWith(h, 'linear'), 'Linear',
            position(h, 'librechat') > 0, 'LibreChat',
            startsWith(h, 'pi-client'), 'Pi',
            startsWith(h, 'antigravity'), 'Antigravity',
            h = 'poke', 'Poke',
            h = 'opencode', 'opencode',
            startsWith(h, 'kiro'), 'Kiro',
            startsWith(h, 'desktop-commander'), 'Desktop Commander',
            'Other'
        ) AS harness
    FROM (
        SELECT
            distinct_id,
            trim(replaceRegexpAll(lower(
                coalesce(
                    multiIf(
                        lower(toString(properties.mcp_vendor_client)) = 'claudecode', 'claude-code',
                        lower(toString(properties.mcp_vendor_client)) = 'claudeai', 'claude-ai',
                        lower(toString(properties.mcp_vendor_client)) = 'cowork', 'cowork',
                        lower(toString(properties.mcp_vendor_client)) = 'claudedesign', 'claude-design',
                        NULL
                    ),
                    if(lower(extract(toString(properties.$mcp_client_user_agent), '^([^/]+)')) = 'claude-code',
                       trim(concat(extract(toString(properties.$mcp_client_user_agent), '^([^/]+)'), ' ', extract(toString(properties.$mcp_client_user_agent), '[(]([^,)]+)'))),
                       NULL),
                    nullIf(nullIf(toString(properties.$mcp_client_name), ''), 'mcp'),
                    nullIf(nullIf(toString(properties.mcp_session_client_name), ''), 'mcp'),
                    nullIf(trim(concat(
                        extract(toString(properties.$mcp_client_user_agent), '^([^/]+)'),
                        ' ',
                        extract(toString(properties.$mcp_client_user_agent), '[(]([^,)]+)')
                    )), ''),
                    nullIf(toString(properties.$mcp_oauth_client_name), ''),
                    ''
                )
            ), '\\s*\\(via mcp-remote[^)]*\\)\\s*', '')) AS h
        FROM events
        WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY
    )
)
GROUP BY harness
ORDER BY users DESC
```

The `multiIf` above is the canonical bucket list. The denominator is total distinct users, so per-harness shares can sum past 100% (one user may use several harnesses). Swap the outer aggregate for other harness cuts — `count()` for call volume, `quantile(0.95)(toFloat(properties.$mcp_duration_ms))` for latency. For `query-trends`, pass the inner `multiIf(...)` over the normalized client name as a **HogQL breakdown** to get the same buckets in a trends series.

**Tool co-occurrence** (which tool tends to run right before a given tool, within a session) — prefer `posthog:query-mcp-tool-neighbors` (`neighborDirection: before`/`after`); this SQL is the recipe behind it, for custom window logic:

```sql
SELECT prev_tool AS tool, count() AS co_occurrences
FROM (
    SELECT $session_id AS conv_id,
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        lagInFrame(coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)))
            OVER (PARTITION BY $session_id ORDER BY timestamp
                  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_tool
    FROM events
    WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 7 DAY
)
WHERE tool = '<tool-name>' AND prev_tool != '' AND prev_tool != tool
GROUP BY prev_tool ORDER BY co_occurrences DESC LIMIT 5
```

Swap `lagInFrame` for `leadInFrame` to get the tool that runs _after_.
