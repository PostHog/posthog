# Debugging a cost regression

"Our LLM bill jumped — why?" is almost always one of: more calls, bigger
prompts, a new model, or a change in cache-hit rate. Work through them in order.

## Step 1 — Confirm and scope the regression

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

## Step 2 — Look for a model mix shift

Run the "cost by model" recipe in [breakdown patterns](./breakdown-patterns.md)
over two windows — the week before and the week after the jump — and diff. A
new `$ai_model` value appearing, or an old one disappearing, is a strong signal.

## Step 3 — Look for prompt bloat

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

## Step 4 — Look for cache degradation

Rerun the "input vs output vs cache economics" recipe in
[breakdown patterns](./breakdown-patterns.md) windowed by day and track
`cache_hit_rate`. A drop often follows a system-prompt change that invalidated
the cached prefix.

## Step 5 — Isolate the feature

Once you've identified the mechanism (more calls / bigger prompts / new model /
worse cache), group by the custom property that separates features (e.g.
`feature`, `workflow_name`) to find which surface is responsible. Then drill
into a representative trace via `posthog:query-llm-trace`.
