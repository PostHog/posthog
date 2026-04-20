---
name: exploring-llm-costs
description: >
  Investigate LLM spend in PostHog — total cost over time, cost by model,
  provider, user, trace, or custom dimension, token and cache-hit economics,
  and cost regressions. Use when the user asks "how much are we spending on
  LLMs?", "which model / user / feature is most expensive?", "why did cost
  spike?", wants to build a cost dashboard or alert, or pastes a trace URL
  and asks about its cost.
---

# Exploring LLM costs

PostHog attaches per-call cost metadata to every `$ai_generation` and `$ai_embedding`
event at ingestion time. Every cost question reduces to an aggregation over those
two event types — the interesting variation is only in how you group, filter, and
compare.

This skill covers the common cost investigations: total spend, breakdowns
(model, provider, user, trace, custom property), token and cache-hit analysis,
regression debugging, and materializing results as insights, dashboards, or alerts.

## Tools

| Tool                                      | Purpose                                                             |
| ----------------------------------------- | ------------------------------------------------------------------- |
| `posthog:get-llm-total-costs-for-project` | One-shot: daily total cost broken down by model (last N days)       |
| `posthog:execute-sql`                     | Ad-hoc HogQL for any cost aggregation — the workhorse of this skill |
| `posthog:query-llm-traces-list`           | List traces with rolled-up cost, token, and error metrics           |
| `posthog:query-llm-trace`                 | Cost breakdown of a single trace across all its events              |
| `posthog:read-data-schema`                | Discover which custom properties exist for breakdowns               |
| `posthog:insight-create`                  | Materialize a cost chart as a saved insight                         |
| `posthog:dashboard-create`                | Bundle cost insights into a dashboard                               |
| `posthog:alert-create`                    | Alert when cost crosses a threshold                                 |

## Cost properties

All costs are USD, recorded per event at ingestion. PostHog derives them from the
model+provider and token counts — you cannot set them manually and trust them to
survive. Costs live on `$ai_generation` and `$ai_embedding` only.

| Property                          | Where                 | Meaning                                         |
| --------------------------------- | --------------------- | ----------------------------------------------- |
| `$ai_total_cost_usd`              | generation, embedding | Total cost for the call                         |
| `$ai_input_cost_usd`              | generation            | Cost attributable to input tokens               |
| `$ai_output_cost_usd`             | generation            | Cost attributable to output tokens              |
| `$ai_input_tokens`                | generation, embedding | Tokens sent to the model                        |
| `$ai_output_tokens`               | generation            | Tokens returned by the model                    |
| `$ai_cache_read_input_tokens`     | generation            | Input tokens served from provider prompt cache  |
| `$ai_cache_creation_input_tokens` | generation            | Input tokens written into provider prompt cache |
| `$ai_model`                       | generation, embedding | Primary breakdown dimension for cost            |
| `$ai_provider`                    | generation, embedding | Secondary breakdown (openai, anthropic, …)      |
| `$ai_is_error`                    | generation            | Exclude/include failed calls in cost totals     |
| `$ai_trace_id`                    | all `$ai_*` events    | Roll costs up to trace level                    |

Note: `$ai_trace` and `$ai_span` events do **not** carry cost. To get a trace's
total cost, sum `$ai_total_cost_usd` across its `$ai_generation` and
`$ai_embedding` events (matched by `$ai_trace_id`).

`distinct_id` is the canonical user dimension — customers typically set it in
the SDK. Use person properties (e.g. `email`, `company_tier`) for richer
per-user breakdowns; discover what exists with `read-data-schema`.

## Workflow: answer "how much are we spending?"

Default to the pre-built MCP tool when the user just wants the headline number:

```json
posthog:get-llm-total-costs-for-project
{ "projectId": <id>, "days": 30 }
```

Returns a trends series of daily total cost broken down by model over the last
N days (default 6). Links back to `/llm-observability` so the user can drill in.

For anything beyond the default shape (different time range, different grouping,
formula), drop to SQL — see the patterns below.

## Workflow: breakdown patterns

Every cost question is a variation of the same template. Always set a time range.
Always include `$ai_embedding` alongside `$ai_generation` if the project uses
embeddings — missing them silently under-counts.

### Total cost in a window

```sql
posthog:execute-sql
SELECT round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost_usd
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
```

### Cost over time (daily)

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    count() AS calls
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
```

### Cost by model

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    properties.$ai_provider AS provider,
    count() AS calls,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_call,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model, provider
ORDER BY cost_usd DESC
```

### Cost by user (top spenders)

```sql
posthog:execute-sql
SELECT
    distinct_id,
    count() AS calls,
    countDistinct(properties.$ai_trace_id) AS traces,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
    AND distinct_id != properties.$ai_trace_id  -- filter out traces used as distinct_id
GROUP BY distinct_id
ORDER BY cost_usd DESC
LIMIT 25
```

For a richer per-user view with person properties, the `/llm-analytics/users`
page uses the same shape — see `products/llm_analytics/frontend/tabs/llmAnalyticsUsersLogic.ts`.

### Cost by trace (top expensive traces)

```sql
posthog:execute-sql
SELECT
    properties.$ai_trace_id AS trace_id,
    count() AS llm_calls,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    min(timestamp) AS started_at
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 7 DAY
    AND isNotNull(properties.$ai_trace_id)
GROUP BY trace_id
ORDER BY cost_usd DESC
LIMIT 25
```

Then drill into the top traces with `posthog:query-llm-trace` to see which spans
and generations are driving cost.

### Cost by custom dimension

Customers often attach their own dimensions (`feature`, `tenant_id`, `workflow_name`).
Discover them first, then group:

1. `posthog:read-data-schema` with `kind: "event_properties"` and
   `event_name: "$ai_generation"` to find custom keys
2. `posthog:read-data-schema` with `kind: "event_property_values"` to spot-check
   that values look right
3. Group by the discovered property:

```sql
posthog:execute-sql
SELECT
    properties.feature AS feature,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    count() AS calls
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
    AND isNotNull(properties.feature)
GROUP BY feature
ORDER BY cost_usd DESC
```

Do not guess custom property names — they vary per project.

### Cost per call (distribution)

Totals hide skew. Use percentiles to see whether a few calls dominate:

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    round(quantile(0.5)(toFloat(properties.$ai_total_cost_usd)), 6) AS p50_cost,
    round(quantile(0.95)(toFloat(properties.$ai_total_cost_usd)), 6) AS p95_cost,
    round(quantile(0.99)(toFloat(properties.$ai_total_cost_usd)), 6) AS p99_cost,
    round(max(toFloat(properties.$ai_total_cost_usd)), 6) AS max_cost
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY model
ORDER BY p99_cost DESC
```

### Input vs output vs cache economics

Output tokens usually cost 3–5× input tokens; cache reads cost ~10% of input.
Split the spend to find optimisation targets:

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    round(sum(toFloat(properties.$ai_input_cost_usd)), 4) AS input_cost,
    round(sum(toFloat(properties.$ai_output_cost_usd)), 4) AS output_cost,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    sum(toInt(properties.$ai_cache_read_input_tokens)) AS cache_read_tokens,
    sum(toInt(properties.$ai_cache_creation_input_tokens)) AS cache_write_tokens,
    round(
        sum(toInt(properties.$ai_cache_read_input_tokens)) /
        nullIf(sum(toInt(properties.$ai_input_tokens)), 0), 3
    ) AS cache_hit_rate
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model
ORDER BY input_cost + output_cost DESC
```

A low `cache_hit_rate` on a model that supports prompt caching is a lever —
prompt structure changes can move cost materially.

## Workflow: inspect a single trace's cost

When the user pastes a trace URL and asks about its cost, fetch the trace and
surface the per-event breakdown:

```json
posthog:query-llm-trace
{ "traceId": "<trace_id>", "dateRange": {"date_from": "-30d"} }
```

Sum `$ai_total_cost_usd` across the returned events, grouped by span name or
model, to show which step(s) drove the cost. The trace response already
includes `totalCost` as a convenience.

## Workflow: debug a cost regression

"Our LLM bill jumped — why?" is almost always one of: more calls, bigger
prompts, a new model, or a change in cache-hit rate. Work through them in order.

### Step 1 — Confirm and scope the regression

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    count() AS calls,
    round(sum(toFloat(properties.$ai_total_cost_usd)) / count(), 6) AS avg_cost_per_call
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 60 DAY
GROUP BY day
ORDER BY day
```

Compare `calls` vs `avg_cost_per_call` before and after the jump. If calls
doubled, it's volume; if cost-per-call rose, it's prompt size, model, or cache.

### Step 2 — Look for a model mix shift

Run the "cost by model" query (above) over two windows — the week before and
the week after the jump — and diff. A new `$ai_model` value appearing, or an
old one disappearing, is a strong signal.

### Step 3 — Look for prompt bloat

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    properties.$ai_model AS model,
    round(avg(toInt(properties.$ai_input_tokens)), 1) AS avg_input_tokens,
    round(avg(toInt(properties.$ai_output_tokens)), 1) AS avg_output_tokens
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, model
ORDER BY day, model
```

### Step 4 — Look for cache degradation

Rerun the "input vs output vs cache economics" query windowed by day and track
`cache_hit_rate`. A drop often follows a system-prompt change that invalidated
the cached prefix.

### Step 5 — Isolate the feature

Once you've identified the mechanism (more calls / bigger prompts / new model /
worse cache), group by the custom property that separates features (e.g.
`feature`, `workflow_name`) to find which surface is responsible. Then drill
into a representative trace via `query-llm-trace`.

## Workflow: materialize as an insight, dashboard, or alert

### Save a cost-over-time insight

```json
posthog:insight-create
{
  "name": "Daily LLM cost",
  "query": {
    "kind": "TrendsQuery",
    "dateRange": {"date_from": "-30d"},
    "series": [{
      "kind": "EventsNode",
      "event": "$ai_generation",
      "math": "sum",
      "math_property": "$ai_total_cost_usd"
    }],
    "trendsFilter": {"aggregationAxisPrefix": "$", "decimalPlaces": 2}
  }
}
```

For "cost per user", add a second series with `math: "dau"` and a formula
`A / B` in `trendsFilter`. For breakdowns, add `breakdownFilter` with
`breakdown: "$ai_model"` or any other dimension.

### Add to a dashboard

After saving the insights, use `posthog:dashboard-create` (or `-update`) to
bundle them. The default `/llm-analytics/dashboard` already includes Cost,
Cost per user, and Cost by model tiles — mirror that structure when building
a custom one.

### Alert on a cost threshold

```json
posthog:alert-create
{
  "insight": "<insight_id>",
  "name": "Daily LLM cost over $100",
  "threshold": {"configuration": {"absoluteThreshold": {"upper": 100}}},
  "condition": {"type": "absolute_value"}
}
```

The insight must be a single-value trends query (e.g. bold-number daily cost).

## Constructing UI links

- **Dashboard**: `https://app.posthog.com/llm-analytics/dashboard`
- **Traces list** (sort by cost): `https://app.posthog.com/llm-analytics/traces`
- **Generations list**: `https://app.posthog.com/llm-analytics/generations`
- **Users list** (per-user cost): `https://app.posthog.com/llm-analytics/users`
- **Single trace**: `https://app.posthog.com/llm-analytics/traces/<trace_id>?timestamp=<url_encoded_iso>`

Always surface a UI link so the user can verify visually.

## Tips

- Always set a time range — cost queries without one scan the full events table
- Always include `$ai_embedding` alongside `$ai_generation` when summing cost; embeddings are cheap per-call but add up at scale
- Costs are written at ingestion from the model+provider lookup — if `$ai_total_cost_usd` is missing or zero, the model wasn't recognised (unusual custom model, fine-tune). Grep for nulls: `countIf(properties.$ai_total_cost_usd IS NULL)` per model
- Exclude errored calls from cost totals only when explicitly asked — providers still charge for many error modes, and including them gives the truthful bill
- For per-user totals, exclude rows where `distinct_id = properties.$ai_trace_id` — some SDKs default distinct_id to the trace ID when no user is set
- Cost is additive across `$ai_generation` + `$ai_embedding` events within a trace; summing on `$ai_span` or `$ai_trace` gives zero
- When answering "why is X expensive?", show the cost **and** the token split — the user almost always wants to know whether to shrink prompts, shrink outputs, or switch models
- Before building a custom dashboard, check whether the stock `/llm-analytics/dashboard` tiles already answer the question — re-creating them is churn
- For large tenants, materialize common cost queries as insights and reuse via `insight-query`; ad-hoc SQL is fine for one-offs but re-running it on every dashboard load is expensive
