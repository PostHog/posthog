# Cost breakdown patterns

Every cost question is a variation of the same template. Always set a time range.
Always include `$ai_embedding` alongside `$ai_generation` if the project uses
embeddings — missing them silently under-counts.

## Cost over time (daily)

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

## Cost by model

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

## Cost by user (top spenders)

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
    AND (
        properties.$ai_trace_id IS NULL
        OR distinct_id != properties.$ai_trace_id
    )  -- filter out rows where distinct_id was defaulted to the trace id
GROUP BY distinct_id
ORDER BY cost_usd DESC
LIMIT 25
```

For a richer per-user view with person properties, the `/llm-analytics/users`
page uses the same shape — check there for inspiration before hand-rolling.

## Cost by trace (top expensive traces)

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

## Cost by custom dimension

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

## Cost per call (distribution)

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

## Input vs output vs cache economics

Output tokens usually cost 3–5× input tokens; cache reads cost ~10% of input.
Split the spend to find optimization targets:

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    round(sum(toFloat(properties.$ai_input_cost_usd)), 4) AS input_cost,
    round(sum(toFloat(properties.$ai_output_cost_usd)), 4) AS output_cost,
    round(sum(toFloat(properties.$ai_request_cost_usd)), 4) AS request_cost,
    round(sum(toFloat(properties.$ai_web_search_cost_usd)), 4) AS web_search_cost,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    sum(toInt(properties.$ai_cache_read_input_tokens)) AS cache_read_tokens,
    sum(toInt(properties.$ai_cache_creation_input_tokens)) AS cache_write_tokens,
    round(
        if(
            any(properties.$ai_cache_reporting_exclusive) = 'true',
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens))
                       + sum(toInt(properties.$ai_cache_read_input_tokens))
                       + sum(toInt(properties.$ai_cache_creation_input_tokens)), 0),
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens)), 0)
        ), 3
    ) AS cache_hit_rate
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model
ORDER BY total_cost DESC
```

The `cache_hit_rate` uses the provider-aware formula from
[cache accounting](./cache-accounting.md) — it branches on
`$ai_cache_reporting_exclusive` so the denominator is correct for both
exclusive and inclusive providers without hardcoding any provider or model
names. If a single model mixes both reporting styles across events
(unusual), split by `$ai_cache_reporting_exclusive` in the GROUP BY
instead of `any()`.

Rank and roll up on `total_cost` — summing only the input/output components
drops request and web-search fees and can diverge from the `/llm-analytics`
UI. If `request_cost` or `web_search_cost` are a meaningful share of
`total_cost` for a model, that's a separate optimization lever (e.g. chattier
provider, tool-heavy generations).

A low `cache_hit_rate` on a model that supports prompt caching is a lever —
prompt structure changes can move cost materially.
