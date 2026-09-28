# MCP tool-call query cookbook

All queries run via `execute-sql` over the `$mcp_tool_call` event. Conventions used
throughout:

- Use **only** `event = '$mcp_tool_call'` — never `IN ('$mcp_tool_call', 'mcp_tool_call')`,
  which double-counts via the transition-shim alias.
- Filter `properties.$mcp_source = 'posthog_mcp_analytics'` — keeps SDK-instrumented events
  (both PostHog's hono server and external customer servers), excludes pre-SDK legacy events.
  If a project's counts look suspiciously low, re-run the coverage probe without this filter
  to check for legacy-only instrumentation.
- Effective tool name (always use this — unwraps the single-exec `exec` dispatcher):
  `coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))`
- **Presence check = `isNotNull(properties.X)`.** This is the one reliable way to test whether an
  enrichment field is populated. Do **not** use `!= ''` or `NOT IN ('', 'None')` as a presence test —
  both resolve unreliably in HogQL for the MCP props (verified: they returned >100% coverage and
  query-shape-dependent counts). `isNotNull` gives clean, consistent coverage.
- **`$mcp_error_type` is quirky — never do value equality on the bare property.** It gives
  _contradictory_ counts across query shapes (a bare `= 'internal'` matched 67k rows a `toString()`
  group showed as absent). Two formulations tested consistent and are the only ones to use:
  - **Classified failures (positive membership):**
    `toString(properties.$mcp_error_type) IN ('internal', 'validation', 'api_4xx', 'api_5xx', 'permission', 'timeout', 'rate_limited', 'missing_context')`.
    In the hono regime the classified share can be a few percent.
  - **Unclassified failures:** compute by **subtraction**, not `NOT IN` (which mishandles the absent
    value): `countIf(toBool($mcp_is_error)) - countIf(toBool($mcp_is_error) AND <the IN whitelist>)`.
    The remainder are tool-result errors (handler returned `{isError:true}` without a class) — ~96% here.
- **Sampling real values:** wrap in `toString(...)` and `GROUP BY` — the absent bucket shows as `'None'`
  in grouped output (safe to read there; just don't turn it into a `WHERE ... IN/NOT IN` predicate).
- **Token fields are numeric, not strings.** `input_tokens` / `output_tokens` (bare keys, no `$`) are
  typed as numbers — test presence with `isNotNull(...)`, never `!= ''` (which errors trying to cast
  `''` to Float64). Read them with `toFloat(...)`.
- The `$mcp_exec_tool_call_name` fallback is genuinely empty/NULL when absent, so the coalesce above is
  correct as written.
- **`$mcp_error_message` does not exist in the hono regime** — it's an external-SDK-only field.
  Referencing it there yields a taxonomy warning and empty results, not an error.
- **Category derivation:** never group rows directly by `properties.$mcp_tool_category` (some rows
  for a tool lack it — notably exec-routed calls captured before dispatch attribution). Derive per-tool
  stats first in an inner subquery grouped by the effective-tool-name coalesce with
  `any(properties.$mcp_tool_category)` as the tool's category, then roll up to category in the outer
  query — query 9 encodes this. Tools with no category anywhere bucket as `Uncategorized`.
- **Alias shadowing in two-level queries:** outer aggregate aliases must not reuse inner column names
  (`sum(errors) AS errors` breaks any later reference to the inner `errors`, e.g. inside
  `groupArrayIf`, with "aggregate function found inside another aggregate function" — verified). Use
  distinct outer names like `category_errors`.
- Tune the `HAVING` volume floors to the project's traffic (read the profile / probe first).

---

## 0. Field-coverage probe (run this first, every run)

Determines the project's regime and which enrichment lenses are usable. `$mcp_is_error` and
`$mcp_duration_ms` are always present; everything below is conditional. Note the `'None'`-aware
absence tests and the `isNotNull` check for the numeric token field.

```sql
SELECT
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS failures,
    countIf(toBool(properties.$mcp_is_error) AND toString(properties.$mcp_error_type) IN ('internal', 'validation', 'api_4xx', 'api_5xx', 'permission', 'timeout', 'rate_limited', 'missing_context')) AS classified_failures,
    round(countIf(toBool(properties.$mcp_is_error) AND toString(properties.$mcp_error_type) IN ('internal', 'validation', 'api_4xx', 'api_5xx', 'permission', 'timeout', 'rate_limited', 'missing_context')) * 100.0 / nullIf(countIf(toBool(properties.$mcp_is_error)), 0), 1) AS pct_failures_classified,
    round(countIf(toBool(properties.$mcp_is_error) AND isNotNull(properties.$mcp_error_message)) * 100.0 / nullIf(countIf(toBool(properties.$mcp_is_error)), 0), 1) AS pct_failures_with_message,
    round(countIf(isNotNull(properties.$mcp_tool_category)) * 100.0 / count(), 1) AS pct_with_category,
    round(countIf(isNotNull(properties.$mcp_intent)) * 100.0 / count(), 1) AS pct_with_intent,
    round(countIf(isNotNull(properties.$mcp_mode)) * 100.0 / count(), 1) AS pct_with_mode,
    round(countIf(isNotNull(properties.input_tokens)) * 100.0 / count(), 1) AS pct_with_tokens,
    uniqIf(toString(properties.$mcp_client_name), isNotNull(properties.$mcp_client_name)) AS distinct_clients
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND timestamp >= now() - INTERVAL 7 DAY
```

Read the result:

- `pct_failures_classified` high → **hono regime with useful classes**: use query 3a. But don't assume
  this is high just because the project is in that regime — most `$mcp_is_error` failures are _tool-result_
  errors (the handler returned `{isError:true}` gracefully) which never get classified, so `error_type`
  stays `'None'`, and the classified share can be a few percent. When
  `pct_failures_classified` is low, the **unclassified-failure bucket is the main story** — lean on
  query 1 (rate), query 2 (struggle), and query 7 (the gap), not the class breakdown.
- `pct_failures_with_message` high (and classified ~0) → **external-SDK regime**: use query 3b to sample messages.
- Both ~0 on a project with real failures → **observability gap**: you can still detect _which_ tools fail
  (query 1) and how agents struggle (query 2), but not _why_ from the taxonomy. That gap is itself
  report-worthy (see the scout's Decide section).
- `pct_with_category` ≥ ~50 → **per-category report grain** (query 9 is the aggregation layer). Hono
  projects land around 70–100% — un-dispatched `exec` rows (discovery verbs, wrapper validation
  errors) carry no category, so don't expect 100% and don't read ~70% as "coverage is broken".
  ~0 → external-SDK regime, fall back to the
  per-tool report grain.
- `pct_with_intent` ≥ ~20 → intent lens (query 5) is worth running. (In the hono regime it is usually near 100%.)
- `distinct_clients` > 1 → the per-client split (query 6) can localize a client-specific break.

---

## 1. Failure leaderboard (Tier-1 detection — always available)

Ranks tools by failures over a volume floor, with rate and reach. Uses only always-on fields.

```sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    any(properties.$mcp_tool_category) AS category,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    uniq(distinct_id) AS users,
    uniqIf($session_id, $session_id != '') AS sessions
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool
HAVING calls >= 50 AND error_rate_pct >= 10
ORDER BY errors DESC
LIMIT 50
```

A tool clearing the floor with a high rate **and** reach across many users/sessions is a
candidate. `category` is `any()` here (per the header's derivation rule) and is the grouping
key for per-category reports — candidates from this query roll up into their category's report.

## 2. Struggle / retry leaderboard (Tier-1 detection — always available, high value)

The signal pure error-rate misses: tools that technically succeed but agents **hammer** or
**retry** within a session, which almost always means a confusing schema or description.
Built from the always-on fields since no retry runner exists.

```sql
SELECT
    tool,
    any(category) AS category,
    count() AS sessions_using_tool,
    countIf(calls >= 3) AS sessions_3plus_calls,
    round(countIf(calls >= 3) * 100.0 / count(), 1) AS pct_sessions_3plus,
    countIf(errors > 0 AND calls > errors) AS sessions_error_then_more_calls,
    round(avg(calls), 1) AS avg_calls_per_session,
    round(avg(errors), 2) AS avg_errors_per_session
FROM (
    SELECT
        $session_id AS session,
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        any(properties.$mcp_tool_category) AS category,
        count() AS calls,
        countIf(toBool(properties.$mcp_is_error)) AS errors
    FROM events
    WHERE event = '$mcp_tool_call'
        AND properties.$mcp_source = 'posthog_mcp_analytics'
        AND $session_id != ''
        AND timestamp >= now() - INTERVAL 7 DAY
    GROUP BY session, tool
)
GROUP BY tool
HAVING sessions_using_tool >= 20
ORDER BY pct_sessions_3plus DESC
LIMIT 50
```

Read it:

- `pct_sessions_3plus` high → agents repeatedly re-call the tool in one session — schema/args
  confusion or the tool not returning what was asked. A strong "needs improvement" signal even
  at a low error rate.
- `sessions_error_then_more_calls` high → fail-then-retry loops (the tool errors, the agent
  reshapes the call and tries again). Points at a misleading schema/description or bad error
  messaging that doesn't tell the agent how to fix the call.

## 3a. Error-class composition — HONO regime (`pct_failures_classified` non-trivial)

For a candidate tool, split failures by class — this is the fix hypothesis. Keep the `'None'`
bucket in the result (don't filter it) so you can see how much of the tool's failure is
_unclassified_ (tool-result errors) vs a nameable class.

```sql
SELECT
    toString(properties.$mcp_error_type) AS error_type,  -- 'None' = unclassified (tool-result error)
    count() AS errors,
    topK(3)(toString(properties.$mcp_error_status)) AS statuses
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND toBool(properties.$mcp_is_error)
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY error_type
ORDER BY errors DESC
```

Class → fix hypothesis:

- `None` (unclassified — usually the biggest bucket) → the tool _returned_ an error result to the
  agent (not found, invalid input handled gracefully, empty result treated as error). These are prime
  "improve the tool" candidates but carry no server-side detail; pair with query 2 (struggle) and
  query 5 (intent) to infer what the agent wanted, or treat as an observability gap (query 7).
- `validation` / `api_4xx` → schema or description misleads agents into malformed calls (docs/schema fix).
- `permission` → a scope/RBAC gap agents keep hitting.
- `timeout` → tool too slow (performance/pagination fix).
- `api_5xx` / `internal` → server-side bug in the tool handler.
- `missing_context` → the tool needs context the agent isn't reliably supplying.
- `rate_limited` → capacity/quota (usually a disqualifier unless sustained + broad).

## 3b. Error-message sampling — EXTERNAL-SDK regime (`pct_failures_with_message` high)

When there's no `$mcp_error_type` but messages are present, cluster the raw text instead.

```sql
SELECT properties.$mcp_error_message AS message, count() AS n
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND toBool(properties.$mcp_is_error)
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND properties.$mcp_error_message != ''
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY message
ORDER BY n DESC
LIMIT 15
```

## 4. Latency leaderboard (Tier-1 — always available)

Slow tools need improvement even at 0% error rate; sustained high p95 also drives `timeout`
failures in the hono regime.

```sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    any(properties.$mcp_tool_category) AS category,
    count() AS calls,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50_ms,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_ms,
    round(quantile(0.99)(toFloat(properties.$mcp_duration_ms))) AS p99_ms
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool
HAVING calls >= 50
ORDER BY p95_ms DESC
LIMIT 30
```

## 5. Intent lens (coverage-gated — only if `pct_with_intent` ≥ ~20)

Ties a tool's failures/struggles to what the agent was actually trying to do — the most
direct route to "what should this tool do differently." Mirrors `MCPToolSampleIntentsQueryRunner`.

```sql
SELECT
    toString(properties.$mcp_intent) AS intent,
    toString(properties.$mcp_intent_source) AS source,
    count() AS n,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND isNotNull(properties.$mcp_intent)
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY intent, source
ORDER BY errors DESC, n DESC
LIMIT 15
```

## 6. Per-client / per-mode split (localize a partial break)

Use `$mcp_client_name` (the most reliable cross-platform harness field) to check whether a
tool is broken universally or only for one client/harness — a different improvement.

```sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    coalesce(nullIf(nullIf(toString(properties.$mcp_client_name), ''), 'None'), 'unknown') AS client,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) = '<tool>'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool, client
HAVING calls >= 20
ORDER BY error_rate_pct DESC
```

In the hono regime you can additionally split by `properties.$mcp_mode` (`'cli'` = single-exec,
`'tools'` = multi-tool): a tool that fails only in `cli` mode points at the `exec`-wrapper
schema rather than the tool itself.

## 7. Observability-gap detection (a report-worthy finding)

Tools that fail materially but carry no diagnosable detail — the improvement is to add error
instrumentation (or a clearer returned-error message) so failures become debuggable. The
"no detail" marker is `error_type IN ('', 'None')` **and** no message — in the hono regime
this is usually the _majority_ of failures (tool-result errors), so tune the ratio/floor to surface the
worst offenders rather than every tool.

```sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    countIf(toBool(properties.$mcp_is_error)) - countIf(toBool(properties.$mcp_is_error) AND toString(properties.$mcp_error_type) IN ('internal', 'validation', 'api_4xx', 'api_5xx', 'permission', 'timeout', 'rate_limited', 'missing_context')) AS undiagnosable_errors
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool
HAVING errors >= 50 AND undiagnosable_errors * 1.0 / errors >= 0.9
ORDER BY undiagnosable_errors DESC
LIMIT 30
```

`undiagnosable_errors` = failures minus classified failures (computed by subtraction — a robust
`NOT IN` on `$mcp_error_type` is not reliable). It also assumes no message; where `$mcp_error_message`
is populated (external-SDK regime), subtract those too or lower the ratio.

## 8. Output-size bloat — HONO regime only (`pct_with_tokens` high)

Tools that return oversized responses bloat agent context — a pagination/summarization
improvement. Token fields are the bare keys `input_tokens` / `output_tokens` (no `$` prefix),
and are estimates, hono-only.

```sql
SELECT
    coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
    count() AS calls,
    round(quantile(0.5)(toFloat(properties.output_tokens))) AS p50_output_tokens,
    round(quantile(0.95)(toFloat(properties.output_tokens))) AS p95_output_tokens
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_source = 'posthog_mcp_analytics'
    AND isNotNull(properties.output_tokens)
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY tool
HAVING calls >= 50
ORDER BY p95_output_tokens DESC
LIMIT 30
```

## 9. By-category rollup (the report grain — per-category mode)

The aggregation layer for per-category reports: per-tool stats in the inner subquery (the
header's derivation rule — effective-tool coalesce + `any()` category), rolled up to category
outside, carrying each category's problem tools as an inline array of
`(tool, calls, errors, error_rate_pct, users)` tuples. Gate on `pct_with_category` ≥ ~50
(query 0); the inner `calls >= 50 AND tool_error_rate_pct >= 10` floor mirrors query 1 — tune
them together. Validated against real telemetry (the tuple `groupArrayIf` works in HogQL; keep
the outer aliases distinct from the inner column names per the header's shadowing rule).

```sql
SELECT
    coalesce(nullIf(nullIf(toString(category), ''), 'None'), 'Uncategorized') AS category_bucket,
    count() AS tools,
    sum(calls) AS category_calls,
    sum(errors) AS category_errors,
    round(sum(errors) * 100.0 / sum(calls), 1) AS category_error_rate_pct,
    countIf(calls >= 50 AND tool_error_rate_pct >= 10) AS problem_tools,
    groupArrayIf((tool, calls, errors, tool_error_rate_pct, users), calls >= 50 AND tool_error_rate_pct >= 10) AS problem_tool_details
FROM (
    SELECT
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        any(properties.$mcp_tool_category) AS category,
        count() AS calls,
        countIf(toBool(properties.$mcp_is_error)) AS errors,
        round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS tool_error_rate_pct,
        uniq(distinct_id) AS users
    FROM events
    WHERE event = '$mcp_tool_call'
        AND properties.$mcp_source = 'posthog_mcp_analytics'
        AND timestamp >= now() - INTERVAL 7 DAY
    GROUP BY tool
)
GROUP BY category_bucket
HAVING problem_tools > 0
ORDER BY category_errors DESC
```

Read it:

- `HAVING problem_tools > 0` keeps healthy categories out of the result — they get no report,
  so they don't belong in the report-grain rollup.
- This is aggregation, not detection — it catches the failure shape only. Struggle (query 2),
  latency (query 4) and session-share (query 10) candidates join their category via the
  `category` column those queries now carry, and they count toward the category's problem tools.
  A category whose only problem tools are struggle/latency/session-share won't appear here (the
  `HAVING` sees only the failure floor) — pull its `category_calls` denominators by re-running
  without the `HAVING`, filtered to that category.
- The `Uncategorized` bucket is dominated by bare `exec` rows (discovery verbs, wrapper
  validation errors) plus uncatalogued tools like `render-ui` — attribution residue to
  sanity-check, not an owning team.
- `category_error_rate_pct` alone is not a finding — a big category dilutes a broken tool; the
  per-tool entries in `problem_tool_details` are what clears the bar.

## 10. Session share — the "called too much" lens

The lens the other four miss: a tool the agent reaches for in a growing share of sessions costs
context and latency in every one of them, and every call succeeds, so failure rate, struggle,
latency, and bloat all read it as healthy. Ranks each tool by the share of its source's sessions
that called it at least once, against the same share over the preceding window. Deterministic —
no judge.

The surface is the bare `source` property (no `$` prefix) that the hono server stamps alongside
the `$mcp_*` fields: `self_driving`, `mcp`, `posthog_code`, `slack`, `posthog_ai`, `wizard`, `cli`.
It is the surface the call came from, not `$mcp_source`, which names the emitting SDK. External-SDK
projects do not stamp it, so those rows bucket as `unknown` and the lens degrades to one
project-wide denominator rather than breaking.

Both windows come out of one 14-day scan split by `is_current`, so the current and prior share are
measured the same way. The per-source denominator is a separate CTE joined back on `source_bucket` —
without it each tool would be scored against its own callers and every share would read 100%.

```sql
WITH per_session AS (
    SELECT
        coalesce(nullIf(nullIf(toString(properties.source), ''), 'None'), 'unknown') AS source_bucket,
        $session_id AS session,
        any(distinct_id) AS user,
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        coalesce(nullIf(nullIf(toString(any(properties.$mcp_tool_category)), ''), 'None'), 'Uncategorized') AS category,
        timestamp >= now() - INTERVAL 7 DAY AS is_current,
        count() AS calls
    FROM events
    WHERE event = '$mcp_tool_call'
        AND properties.$mcp_source = 'posthog_mcp_analytics'
        AND $session_id != ''
        AND timestamp >= now() - INTERVAL 14 DAY
    GROUP BY source_bucket, session, tool, is_current
),
totals AS (
    SELECT
        source_bucket,
        uniqIf(session, is_current) AS sessions_total,
        uniqIf(session, NOT is_current) AS prior_sessions_total
    FROM per_session
    GROUP BY source_bucket
)
SELECT
    t.source_bucket AS source,
    t.tool AS tool,
    any(t.category) AS category,
    uniqIf(t.session, t.is_current) AS sessions_with_call,
    uniqIf(t.user, t.is_current) AS users_with_call,
    any(d.sessions_total) AS sessions_total,
    round(uniqIf(t.session, t.is_current) * 100.0 / nullIf(any(d.sessions_total), 0), 1) AS session_share_pct,
    round(avgIf(t.calls, t.is_current), 2) AS calls_per_session,
    any(d.prior_sessions_total) AS prior_sessions_total,
    if(any(d.prior_sessions_total) >= 20, round(uniqIf(t.session, NOT t.is_current) * 100.0 / any(d.prior_sessions_total), 1), NULL) AS share_pct_prior_window
FROM per_session AS t
JOIN totals AS d ON d.source_bucket = t.source_bucket
WHERE t.tool != 'exec'
GROUP BY source, tool
HAVING sessions_with_call >= 20
ORDER BY source, session_share_pct DESC
LIMIT 20 BY source
```

Read it:

- **The step change is the finding, not the level.** A tool that sits high and flat is doing its
  job. A tool whose share jumped between `share_pct_prior_window` and `session_share_pct`, across
  many sessions, is being advertised too eagerly — the fix hypothesis points at prompt or
  tool-description wording, not the handler.
- `share_pct_prior_window` is null when the source had fewer than 20 sessions in the prior window,
  the same floor as the current reach. A share over a few prior sessions reads as 0% or 100% by
  chance, so a surface a team is only starting to use would look like a jump on every tool. A null
  prior share is no baseline, so the row is not a step-change candidate. `prior_sessions_total` is
  the prior denominator to cite as evidence.
- `users_with_call` is the reach check. Twenty sessions from one `distinct_id` pass the session
  floor and are still one developer, so the single-user disqualifier applies here as everywhere.
  The category falls back to `Uncategorized` the same way query 9 does, because the record schema
  requires a string and one null category would reject the whole batch.
- Keep the source split. A tool called in most sessions of one surface and almost none of another
  localizes the cause to that surface's prompt.
- `calls_per_session` separates "reached for once, everywhere" from "hammered" — the latter is
  query 2's territory, and the two together say whether the tool is over-advertised or confusing.
- **Bare `exec` is filtered out.** The wrapper is present in nearly every session by construction,
  so it would top this query on every project and mean nothing. The `totals` CTE still counts its
  sessions, so the denominator stays every MCP session of the source. The same disqualifiers as
  everywhere else apply: a share over a handful of sessions is one developer.
- `LIMIT 20 BY source` returns the top 20 tools of each source, so one busy source cannot crowd
  another out. These rows are what the scout records as `tool_session_share` — the schema's fields
  only. `users_with_call` and `prior_sessions_total` are evidence for the report, not record fields,
  and the closed schema rejects a batch that carries them.
- For detection, rank by the change instead of the level. Run it again with
  `ORDER BY source, session_share_pct - share_pct_prior_window DESC NULLS LAST`, so a tool that
  rose from a low share is not cut behind tools that sit high and flat.

## 11. Category metrics — the `category_rollup` record

The source for every measured field of a `category_rollup` record: one row per category with any
traffic, healthy ones included, plus the project-wide `all` row. The per-tool queries cannot stand
in for it. Summing per-tool `users` or `sessions` counts a user once per tool they called, and a
per-tool p95 or struggle share does not average into a category value. Their volume floors also
drop tools, so they do not cover the whole category.

Every metric comes from raw rows at category grain. `tool_category` applies the header's
derivation rule, and joining it back to the raw rows keeps exec-routed calls that lack the property
in their tool's category. `arrayJoin` counts each row twice, once in its category and once in `all`,
so the baseline row is measured the same way in the same scan. Struggle uses query 2's session
definition: a session struggled in a category when any of its tools there was called three or more
times, or failed and was called again.

```sql
WITH calls AS (
    SELECT
        coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name)) AS tool,
        properties.$mcp_tool_category AS raw_category,
        $session_id AS session,
        distinct_id,
        toBool(properties.$mcp_is_error) AS is_error,
        toFloat(properties.$mcp_duration_ms) AS duration_ms
    FROM events
    WHERE event = '$mcp_tool_call'
        AND properties.$mcp_source = 'posthog_mcp_analytics'
        AND timestamp >= now() - INTERVAL 7 DAY
),
tool_category AS (
    SELECT
        tool,
        coalesce(nullIf(nullIf(toString(any(raw_category)), ''), 'None'), 'Uncategorized') AS category_bucket
    FROM calls
    GROUP BY tool
),
struggle AS (
    SELECT
        category,
        count() AS measured_sessions,
        countIf(session_struggled) AS struggle_sessions
    FROM (
        SELECT
            arrayJoin([c.category_bucket, 'all']) AS category,
            s.session AS session,
            max(s.session_calls >= 3 OR (s.session_errors > 0 AND s.session_calls > s.session_errors)) AS session_struggled
        FROM (
            SELECT session, tool, count() AS session_calls, countIf(is_error) AS session_errors
            FROM calls
            WHERE session != ''
            GROUP BY session, tool
        ) AS s
        JOIN tool_category AS c ON c.tool = s.tool
        GROUP BY category, session
    )
    GROUP BY category
),
volume AS (
    SELECT
        arrayJoin([c.category_bucket, 'all']) AS category,
        count() AS category_calls,
        countIf(k.is_error) AS category_errors,
        uniqIf(k.session, k.session != '') AS category_sessions,
        uniq(k.distinct_id) AS category_users,
        quantile(0.95)(k.duration_ms) AS category_p95_ms
    FROM calls AS k
    JOIN tool_category AS c ON c.tool = k.tool
    GROUP BY category
)
SELECT
    v.category AS category,
    v.category_calls AS calls,
    v.category_errors AS errors,
    v.category_sessions AS sessions,
    v.category_users AS users,
    round(v.category_errors * 100.0 / v.category_calls, 1) AS error_rate_pct,
    round(s.struggle_sessions * 100.0 / nullIf(s.measured_sessions, 0), 1) AS struggle_session_pct,
    round(v.category_p95_ms) AS p95_duration_ms,
    round(v.category_calls * 100.0 / max(v.category_calls) OVER (), 1) AS share_of_project_calls_pct
FROM volume AS v
LEFT JOIN struggle AS s ON s.category = v.category
ORDER BY calls DESC
```

Read it:

- Each column maps to the `mcp_`-prefixed record field of the same name. `mcp_problem_tools` and
  `mcp_report_action` are the scout's own judgment, so they do not come from here.
- `share_of_project_calls_pct` divides by the largest row, which is always `all`.
- `struggle_session_pct` is null for a category whose calls carry no `$session_id`, and
  `p95_duration_ms` is null when no call carries a duration. Record them as null, not zero.
- The numbers change only when the data does. Do not re-derive them from other queries on a run
  that skips this one, because a change of method shows on the chart as a step in the metric.
