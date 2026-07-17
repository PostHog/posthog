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
    On PostHog's own data only ~4% of failures are classified.
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
- **`$mcp_error_message` does not exist on PostHog's own (hono) data** — it's an external-SDK-only field.
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
  this is high just because you're on PostHog's own data — most `$mcp_is_error` failures are _tool-result_
  errors (the handler returned `{isError:true}` gracefully) which never get classified, so `error_type`
  stays `'None'`. On PostHog's own project only ~4% of failures carry a real class. When
  `pct_failures_classified` is low, the **unclassified-failure bucket is the main story** — lean on
  query 1 (rate), query 2 (struggle), and query 7 (the gap), not the class breakdown.
- `pct_failures_with_message` high (and classified ~0) → **external-SDK regime**: use query 3b to sample messages.
- Both ~0 on a project with real failures → **observability gap**: you can still detect _which_ tools fail
  (query 1) and how agents struggle (query 2), but not _why_ from the taxonomy. That gap is itself
  report-worthy (see the scout's Decide section).
- `pct_with_category` ≥ ~50 → **per-category report grain** (query 9 is the aggregation layer). Hono
  projects land around 70–100% — un-dispatched `exec` rows (discovery verbs, wrapper validation
  errors) carry no category, so don't expect 100% and don't read ~70% as "coverage is broken"
  (verified: PostHog's own project sits at ~72%). ~0 → external-SDK regime, fall back to the
  per-tool report grain.
- `pct_with_intent` ≥ ~20 → intent lens (query 5) is worth running. (On PostHog's own data this is ~100%.)
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
"no detail" marker is `error_type IN ('', 'None')` **and** no message — on PostHog's own data
this is the _majority_ of failures (tool-result errors), so tune the ratio/floor to surface the
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
- This is aggregation, not detection — it catches the failure shape only. Struggle (query 2)
  and latency (query 4) candidates join their category via the `category` column those queries
  now carry; a category whose only problem tools are struggle/latency won't appear here (the
  `HAVING` sees only the failure floor) — pull its `category_calls` denominators by re-running
  without the `HAVING`, filtered to that category.
- The `Uncategorized` bucket is dominated by bare `exec` rows (discovery verbs, wrapper
  validation errors) plus uncatalogued tools like `render-ui` — attribution residue to
  sanity-check, not an owning team (verified: on PostHog's own project it is exactly those two
  tools at high volume).
- `category_error_rate_pct` alone is not a finding — a big category dilutes a broken tool; the
  per-tool entries in `problem_tool_details` are what clears the bar.
