# MCP analytics (`$mcp_tool_call` events)

Any MCP server instrumented with the `@posthog/mcp` SDK — and PostHog's own MCP server — emits a `$mcp_tool_call` event on the shared `events` table every time an agent invokes a tool. There is **no dedicated ClickHouse table** — all fields live as `$mcp_*` properties on `events`, queried directly with `posthog:execute-sql`. This is the data behind the MCP analytics dashboard, tool-quality, and tool-detail screens; every metric on those screens is reproducible as HogQL over this event.

Query the canonical `$`-prefixed event name. Servers instrumented with the `@posthog/mcp` SDK emit only `$mcp_tool_call` / `$mcp_initialize`; PostHog's own hosted server additionally dual-emits legacy un-prefixed `mcp_tool_call` / `mcp_initialize` aliases through a transition shim. Match the canonical name only — an `event IN ('mcp_tool_call', '$mcp_tool_call')` would double-count PostHog's own server.

**For a single tool, prefer the typed tools.** Each takes a `toolName` plus a `dateRange`, runs the same query runner the tool-detail UI uses, and is gated behind the `mcp-analytics` flag, so results match the UI exactly and you don't re-derive the SQL below. `toolName` is the effective name (resolved server-side — the inner tool of a single-exec wrapper call) for all of them, including `posthog:query-mcp-tool-failures`:

| question about one tool                                             | tool                                         |
| ------------------------------------------------------------------- | -------------------------------------------- |
| headline numbers (calls, errors, p50/p95, users, sessions, intents) | `posthog:query-mcp-tool-stats`               |
| day-by-day trend                                                    | `posthog:query-mcp-tool-daily-stats`         |
| top failure buckets, by harness                                     | `posthog:query-mcp-tool-failures`            |
| individual errored calls in one failure bucket                      | `posthog:query-mcp-tool-failure-occurrences` |
| top callers (incl. person email/name)                               | `posthog:query-mcp-tool-top-users`           |
| tools called before/after it (`neighborDirection: before`/`after`)  | `posthog:query-mcp-tool-neighbors`           |
| recent agent intents                                                | `posthog:query-mcp-tool-sample-intents`      |
| distinct descriptions seen                                          | `posthog:query-mcp-tool-descriptions`        |

And `posthog:query-mcp-harness-breakdown` for the cross-tool harness cut (see below).

**Sessions have typed tools too.** A session is one agent run — the `$mcp_tool_call` events sharing a `$session_id`:

| question about sessions                                 | tool                                             |
| ------------------------------------------------------- | ------------------------------------------------ |
| list sessions (calls, start/end, tools, client, person) | `posthog:mcp-analytics-sessions-list`            |
| one session's calls, chronological                      | `posthog:mcp-analytics-sessions-tool-calls`      |
| LLM summary of one session's goal                       | `posthog:mcp-analytics-sessions-generate-intent` |

Three things to know before using them:

- **7-day lookback by default.** `posthog:mcp-analytics-sessions-tool-calls` and `posthog:mcp-analytics-sessions-generate-intent` both scan 7 days back, so an older session returns empty unless you pass its `session_start` as `date_from`. Carry that value forward from the list row.
- **They report the raw `$mcp_tool_name`**, not the effective inner tool of a single-exec wrapper call — unlike the per-tool tools above.
- **The session list has no error filter or error count.** "Which sessions failed?" is a SQL question.

And two tools cover what SQL can't express at all: `posthog:mcp-analytics-intent-clusters-retrieve` and `posthog:mcp-analytics-intent-clusters-recompute` (embedding-based intent clustering).

**HogQL is the path for everything else** — cross-tool rankings (the tool-quality matrix), custom breakdowns, errored-session filtering, effective tool names within a session — query them with `execute-sql`. It is also the fallback when the `mcp-analytics` flag is off: every typed tool above is gated behind it, `execute-sql` is not.

## Key properties

`Source` says where the property comes from: **SDK** — set by `@posthog/mcp` (`packages/mcp/src/extensions/constants.ts`), present on any instrumented customer server; **server** — stamped only by PostHog's own hosted MCP server (`services/mcp`), so it exists only for PostHog's dogfood data; **exec** — only present when the server runs in single-exec mode (one `exec` dispatcher tool instead of one tool per name).

| Property                          | Source | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_tool_name`                  | SDK    | Registered tool name.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `$mcp_exec_tool_call_name`        | exec   | Inner tool name when the call went through the new-SDK single-exec wrapper. See effective-tool-name note below.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `$mcp_exec_tool_call_description` | exec   | Inner tool's description — the dispatcher's own `$mcp_tool_description` is static "exec" boilerplate on every call, so this is the useful one in single-exec mode.                                                                                                                                                                                                                                                                                                                                                               |
| `$mcp_is_error`                   | SDK    | Whether the call failed. Always read via `toBool(properties.$mcp_is_error)`.                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `$mcp_error_type`                 | SDK    | Semantic failure bucket when `$mcp_is_error` is true (`internal`, `validation`, `api_4xx`, `api_5xx`, `permission`, `timeout`, `rate_limited`, `missing_context`). Only newer SDK/server paths set it.                                                                                                                                                                                                                                                                                                                           |
| `$mcp_error_status`               | server | HTTP status code for an errored call, when the failure came from an HTTP call. Stamped by PostHog's own server (`services/mcp/src/hono/tool-executor.ts`) — not part of the SDK's field set, so an externally-instrumented server on the SDK alone won't emit it.                                                                                                                                                                                                                                                                |
| `$mcp_duration_ms`                | SDK    | Wall-clock duration; cast with `toFloat(...)`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `$session_id`                     | —      | Session id — the grouping key for a single agent run, and the same id as `$mcp_session_id` (`$session_id` is its materialised column). Use the bare `$session_id` field, not `properties.$session_id`: the `properties.` accessor renders null-wrapped in SELECT but as the raw column in HAVING/ORDER, so a search HAVING would mismatch the GROUP BY key. Some per-tool runners still read `coalesce(properties.$mcp_session_id, properties.$session_id)` — same id, just a defensive fallback. See "Three identifiers" below. |
| `$mcp_intent`                     | SDK    | The agent's stated intent for the call, when supplied.                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `$mcp_intent_source`              | SDK    | Where `$mcp_intent` came from: `context_parameter` (client supplied it directly on the call) or `inferred` (server derived it via `intentFallback`).                                                                                                                                                                                                                                                                                                                                                                             |
| `$mcp_conversation_id`            | SDK    | Stable, agent-echoed identifier that survives reconnects. See "Three identifiers" below. Only present when the server has `enableConversationId` turned on.                                                                                                                                                                                                                                                                                                                                                                      |
| `$mcp_parameters`                 | SDK    | Arguments passed to the tool call. Large strings and sensitive keys are redacted before capture.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `$mcp_response`                   | SDK    | The response the MCP server returned, redacted the same way as `$mcp_parameters`. Stays empty on PostHog's hosted server.                                                                                                                                                                                                                                                                                                                                                                                                        |
| `$mcp_client_name`                | SDK    | Raw client string (e.g. `claude-code/1.2.3`). Bucketed into harnesses **server-side** by `products/mcp_analytics/backend/mcp_harness.py` (`HARNESS_TOKEN_SQL` / `harness_label_sql`) — the single source of truth. The frontend only maps the resolved label to a logo. There is no `category` column.                                                                                                                                                                                                                           |
| `$mcp_client_version`             | SDK    | Version of the MCP client that initiated the connection.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `$mcp_tool_category`              | server | Tool category, when tagged. Stamped from PostHog's tool catalog; external servers can declare one per tool.                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `$mcp_tool_description`           | SDK    | Tool description as seen by the agent (revisions over time), clipped to 512 chars on capture. Gap warning: the hono migration silently dropped this stamp, so there is a window (roughly Jun-Jul 2026) with no descriptions on PostHog's hosted server; `notEmpty(...)` filters are mandatory.                                                                                                                                                                                                                                   |
| `$mcp_listed_tool_names`          | SDK    | Every tool name advertised on a `tools/list` call, in multi-tool mode (JSON array; filter with `contains`). Diff against `$mcp_tool_name` to find zombie tools (advertised, never called). In single-exec mode, `$mcp_exec_inner_tool_names` carries the catalog instead.                                                                                                                                                                                                                                                        |
| `$mcp_exec_inner_tool_names`      | exec   | Every inner tool name available at `tools/list` time, in single-exec mode (JSON array; filter with `contains`). Diff against `$mcp_exec_tool_call_name` to find zombie tools.                                                                                                                                                                                                                                                                                                                                                    |
| `$mcp_server_name`                | SDK    | Advertised name of the MCP server that handled the request (e.g. `PostHog`).                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `$mcp_server_version`             | SDK    | Advertised version of the MCP server that handled the request.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `$mcp_protocol_version`           | SDK    | MCP spec version negotiated at `initialize` (added in SDK v0.10.0). Stamped on `$mcp_initialize` and on every subsequent event of the session.                                                                                                                                                                                                                                                                                                                                                                                   |
| `$mcp_resource_name`              | SDK    | Name of the MCP resource/prompt/tool the event refers to (resource-read and prompt-get events).                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `$mcp_source`                     | SDK    | Constant identifier for the analytics SDK that emitted the event (e.g. `posthog_mcp_analytics`). Lets you separate SDK-emitted events from other/legacy MCP paths.                                                                                                                                                                                                                                                                                                                                                               |

**Server-stamped extras (PostHog's own server only, not the SDK):** `$mcp_session_id` (transport-level session handle — see "Three identifiers" below), `$mcp_region` (cloud region that handled the request, e.g. `us`/`eu`), `$mcp_mode` (`cli` for single-exec, `tools` for one-tool-per-name), `$mcp_consumer` (upstream surface, e.g. `posthog-code`/`slack`), and the non-`$`-prefixed `mcp_vendor_client` (vendor/client identity from the `x-anthropic-client` header, e.g. `ClaudeCode`/`ClaudeAI` — used to resolve the harness in the bucketing SQL below) and `mcp_runtime` (server runtime, e.g. `hono`), plus `$mcp_auth_method` (which credential the request authenticated with, from the bearer token's prefix: `oauth`, `personal_api_key`, `id_jag`, `none`, `unknown`).

**Refused requests are a separate event.** A request the PostHog API rejects dies before any session, organization, or project is resolved, so it emits none of the events above — it emits `$mcp_auth_failed` instead, with `$mcp_auth_failure_reason` (`insufficient_scope`, `inactive_oauth_token`, `invalid_api_key`, `unknown`), `$mcp_missing_scope` when the API named a scope, and `$mcp_auth_status` (401/403). Only PostHog's own server emits it, so it is absent for customer-instrumented servers.

It does not set `$mcp_is_error`/`$mcp_error_status`, which mean "a tool call failed against the PostHog API" — so an auth refusal never inflates tool error rates, and the status it did return lives in `$mcp_auth_status` instead.

Two consequences for queries: it has no `$mcp_organization_id`/`$mcp_project_id`, and its `distinct_id` is a hash of the bearer token rather than a user id, so count it with `uniq(distinct_id)` for affected credentials and join to other MCP events by client and time, never by person. A connector looping on authorization shows up here; before this event existed the same outage looked like an absence of traffic.

**Three identifiers, not one.** `$session_id` is the materialised column — `GROUP BY`/join on this one. `$mcp_session_id` is the transport-level handle the MCP SDK observed (MCP `extra.sessionId` or a framework session cookie); it rotates on process restart, reconnect, or framework boundary. `$mcp_conversation_id` is agent-echoed and stable across reconnects — reach for it when a "session" needs to survive a client reconnecting mid-task. In practice `$session_id` and `$mcp_session_id` carry the same value; `$mcp_conversation_id` is the more durable one when they diverge.

**Effective tool name.** New-SDK events wrap the real tool in a single-exec call, so to filter/group by the tool the agent actually invoked, use:

```sql
coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))
```

**The advertised catalog: `$mcp_tools_list`.** Each tools/list response emits a `$mcp_tools_list` event whose `$mcp_listed_tool_names` property holds the advertised tool names as a JSON array, with `tool_count` alongside. This is the denominator for "advertised but never called" analysis. Only about half of tool-call sessions carry a tools-list event, and sessions in exec-wrapper mode advertise just the wrapper (`['exec', 'render-ui']`), so condition per-tool discovery cuts on sessions where the catalog was actually observed. Extract the array with:

```sql
JSONExtract(coalesce(toString(properties.$mcp_listed_tool_names), '[]'), 'Array(String)')
```

The `coalesce(..., '[]')` is required: the property accessor is Nullable, and `JSONExtract` of a Nullable into `Array(String)` is a ClickHouse type error.

**Failures with detail.** `$mcp_tool_call` carries `$mcp_is_error` plus a semantic `$mcp_error_type` and, for HTTP failures, `$mcp_error_status` (see the Source column above: `$mcp_error_type` is an SDK field that PostHog's own server also stamps itself, while `$mcp_error_status` is stamped only by PostHog's server, so a separately-instrumented server on the SDK alone won't emit it). `posthog:query-mcp-tool-failures` groups errored tool calls by these two fields and returns each bucket's raw `error_type`/`error_status`; pass those to `posthog:query-mcp-tool-failure-occurrences` for individual errored calls with the free-text `$mcp_error_message` (sanitized, truncated to 2048 chars — empty on events captured before PostHog's server started emitting it). `$mcp_response` stays empty on PostHog's hosted server. PostHog's own tool calls also don't emit `$exception` events — those only exist for separately-instrumented MCP servers.

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

**Tool-quality matrix** (error rate + latency percentiles + reach, one row per tool) — this cross-tool ranking has no typed tool; once you've picked a tool, drill into it with `posthog:query-mcp-tool-stats`, `posthog:query-mcp-tool-failures`, or `posthog:query-mcp-tool-daily-stats`:

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

**Prefer the typed tool.** For "which harnesses use our MCP, and how reliably?", call the `posthog:query-mcp-harness-breakdown` tool (gated behind the `mcp-analytics` flag). It returns calls / errors / error-rate / sessions per harness and accepts the same `dateRange` / `properties` / `filterTestAccounts` filters as the dashboard, so results match the UI exactly — no hand-written bucketing needed. It also accepts an optional `toolName` to scope the breakdown to one effective tool — but note that scoping **also restricts the result to new-SDK events** (`$mcp_source = 'posthog_mcp_analytics'`), so old-SDK and third-party calls for that tool are excluded and a harness can be undercounted. For a one-tool harness cut across all SDK sources, use `execute-sql`. Anything the typed tools don't express drops to `execute-sql` below.

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
            -- Codex has two spellings: the `codex-mcp-client` clientInfo.name caught by
            -- the prefix below, and this User-Agent surface. This branch must precede the
            -- generic `openai-mcp` prefix, which would otherwise report it as "OpenAI".
            h = 'openai-mcp codex', 'OpenAI Codex',
            startsWith(h, 'openai-mcp'), 'OpenAI',
            startsWith(h, 'codex'), 'OpenAI Codex',
            startsWith(h, 'grok'), 'Grok',
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
            h = 'posthog-cli', 'PostHog CLI',
            -- Ranked top-N lists name an unrecognized client verbatim instead
            -- (`harness_label_or_token_sql`); "Other" is for callers that need the label
            -- confined to the bounded set, e.g. one aggregated into a per-row array.
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
                    -- grok.com Connectors carries `grok-` only in the UA; its clientInfo.name
                    -- is the generic "connectors-manager", so promote the grok UA above it.
                    if(startsWith(lower(extract(toString(properties.$mcp_client_user_agent), '^([^/]+)')), 'grok'),
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
