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

| Tool                            | Purpose                                                             |
| ------------------------------- | ------------------------------------------------------------------- |
| `posthog:execute-sql`           | Ad-hoc HogQL for any cost aggregation — the workhorse of this skill |
| `posthog:query-llm-traces-list` | List traces with rolled-up cost, token, and error metrics           |
| `posthog:query-llm-trace`       | Cost breakdown of a single trace across all its events              |
| `posthog:read-data-schema`      | Discover which custom properties exist for breakdowns               |
| `posthog:insight-create`        | Materialize a cost chart as a saved insight                         |
| `posthog:dashboard-create`      | Bundle cost insights into a dashboard                               |
| `posthog:alert-create`          | Alert when cost crosses a threshold                                 |

## Cost properties

All costs are USD, recorded per event at ingestion. PostHog derives them from the
model+provider and token counts — you cannot set them manually and trust them to
survive. Costs live on `$ai_generation` and `$ai_embedding` only.

| Property                          | Where                 | Meaning                                                                 |
| --------------------------------- | --------------------- | ----------------------------------------------------------------------- |
| `$ai_total_cost_usd`              | generation, embedding | Total cost for the call — **authoritative total**, use this for rollups |
| `$ai_input_cost_usd`              | generation, embedding | Cost attributable to input tokens                                       |
| `$ai_output_cost_usd`             | generation, embedding | Cost attributable to output tokens                                      |
| `$ai_request_cost_usd`            | generation, embedding | Per-request flat cost (e.g. Anthropic per-request fee); often `0`       |
| `$ai_web_search_cost_usd`         | generation, embedding | Cost of web-search tool calls inside the generation; often `0`          |
| `$ai_audio_cost_usd`              | generation            | Audio-modality cost when the model charges a separate rate; often `0`   |
| `$ai_image_cost_usd`              | generation            | Image-modality cost; often `0`                                          |
| `$ai_video_cost_usd`              | generation            | Video-modality cost; often `0`                                          |
| `$ai_input_tokens`                | generation, embedding | Tokens sent to the model (total across modalities)                      |
| `$ai_output_tokens`               | generation            | Tokens returned by the model (total across modalities)                  |
| `$ai_total_tokens`                | generation, embedding | Input + output tokens                                                   |
| `$ai_cache_read_input_tokens`     | generation            | Input tokens served from provider prompt cache                          |
| `$ai_cache_creation_input_tokens` | generation            | Input tokens written into provider prompt cache                         |
| `$ai_reasoning_tokens`            | generation            | Reasoning-model thinking tokens (charged as output)                     |
| `$ai_model`                       | generation, embedding | Primary breakdown dimension for cost                                    |
| `$ai_provider`                    | generation, embedding | Secondary breakdown (openai, anthropic, …)                              |
| `$ai_is_error`                    | generation            | Exclude/include failed calls in cost totals                             |
| `$ai_trace_id`                    | all `$ai_*` events    | Roll costs up to trace level                                            |
| `$ai_session_id`                  | all `$ai_*` events    | Roll costs up to session level (group sequences of related traces)      |

**Always sum `$ai_total_cost_usd`, not the components.** At ingestion,
`$ai_total_cost_usd = input + output + request + web_search` (plus any
modality costs). Summing only `$ai_input_cost_usd + $ai_output_cost_usd`
silently drops request and web-search fees — real and non-zero for
Anthropic request fees and any tool-augmented generation. The UI's cost
cells sum `$ai_total_cost_usd` over `event IN ('$ai_generation',
'$ai_embedding')`; mirror that. See [Calculating LLM costs](https://posthog.com/docs/llm-analytics/calculating-costs)
for the full derivation.

Note on cache costs: providers that report cache tokens exclusively of
`$ai_input_tokens` (e.g. Anthropic) also surface cache-read/write spend
outside `$ai_input_cost_usd`, so `$ai_input_cost_usd` understates the true
input-side spend there; providers that report inclusively (e.g. OpenAI)
bundle cache spend into `$ai_input_cost_usd`. This varies by SDK version
as well — see the "Cache token accounting" section below for the
provider-aware formula. `$ai_total_cost_usd` is always the authoritative
total and already accounts for whichever style the event used.

Note: `$ai_trace` and `$ai_span` events do **not** carry cost for rollup
purposes. To get a trace's total cost, sum `$ai_total_cost_usd` across its
`$ai_generation` and `$ai_embedding` events (matched by `$ai_trace_id`).
Some SDK wrappers duplicate `$ai_total_cost_usd` onto `$ai_trace` as a
convenience, but query runners still aggregate over
`event IN ('$ai_generation', '$ai_embedding')` — don't mix event sets or
you'll double-count.

`$ai_evaluation` events also emit cost properties (ingestion treats them
as costed alongside `$ai_generation` and `$ai_embedding`), but the stock
`/llm-analytics` rollups and the query runners **do not** include them
in cost totals. If the user wants "total spend including evaluations",
add `$ai_evaluation` to the event filter explicitly (e.g.
`event IN ('$ai_generation', '$ai_embedding', '$ai_evaluation')`) and
call out that it's an expanded definition; otherwise stick to the
generation + embedding set to match the UI.

`distinct_id` is the canonical user dimension — customers typically set it in
the SDK. Use person properties (e.g. `email`, `company_tier`) for richer
per-user breakdowns; discover what exists with `read-data-schema`.

## How costs get set: SDK, custom pricing, ingestion

Costs can arrive on the event in three ways; ingestion applies them in this
precedence (see [Calculating LLM costs](https://posthog.com/docs/llm-analytics/calculating-costs)
for the authoritative rules):

1. **Pre-calculated** — the SDK / manual capture sets `$ai_input_cost_usd`,
   `$ai_output_cost_usd`, `$ai_request_cost_usd`, `$ai_web_search_cost_usd`
   directly. Ingestion preserves them and fills `$ai_total_cost_usd` as the
   sum. Use when the caller already knows the cost.
2. **Custom pricing** — the SDK sets `$ai_input_token_price` /
   `$ai_output_token_price` (required pair) plus optionally
   `$ai_cache_read_token_price`, `$ai_cache_write_token_price`,
   `$ai_request_price`, `$ai_web_search_price`. Ingestion multiplies by the
   token counts. Token prices are **per token**, not per million.
3. **Automatic model matching** — ingestion looks up pricing by
   `$ai_model` + `$ai_provider` (OpenRouter first, manual fallback).

Three metadata properties tell you which path was taken — read them whenever
a cost looks wrong:

| Property                  | Meaning                                                                     |
| ------------------------- | --------------------------------------------------------------------------- |
| `$ai_model_cost_used`     | Canonical model id the pricing lookup matched (may differ from `$ai_model`) |
| `$ai_cost_model_source`   | `openrouter` \| `manual` \| `custom` \| `passthrough`                       |
| `$ai_cost_model_provider` | Provider the lookup used                                                    |

When `$ai_total_cost_usd` is null or zero for a model, group by model
**and** `$ai_cost_model_source` so you can see, per model, how many of
its zero-cost calls came from each ingestion path. A model that has only
`source = NULL` rows means ingestion never matched a pricing entry (fix:
add custom pricing or correct `$ai_model` / `$ai_provider`); a model
with `source = 'custom'` and zero cost is an explicitly-zero custom
price (usually a misconfigured `$ai_input_token_price` / `$ai_output_token_price`).
Without the source grouping the two look the same.

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    properties.$ai_cost_model_source AS source,
    count() AS calls,
    countIf(toFloat(properties.$ai_total_cost_usd) = 0 OR properties.$ai_total_cost_usd IS NULL) AS zero_cost_calls
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY model, source
ORDER BY zero_cost_calls DESC
```

## Cache token accounting (exclusive vs inclusive)

Providers report cache tokens two ways, and the skill's cache-hit-rate math
changes accordingly:

- **Exclusive** — `$ai_input_tokens` does **not** include cache tokens.
  Total input volume is `input_tokens + cache_read + cache_creation`.
  Anthropic currently reports this way on most SDKs.
- **Inclusive** — `$ai_input_tokens` already includes cache tokens.
  OpenAI and most others currently report this way.

Don't hardcode provider behaviour — it varies by SDK and by SDK version,
and providers can change their own reporting style over time. Instead,
trust the per-event flag: ingestion auto-detects and writes the resolved
value to `$ai_cache_reporting_exclusive` (boolean) on every
`$ai_generation`. Callers can also override with
`$ai_cache_reporting_exclusive: true|false` when manually capturing. When
computing a cache-hit rate, split by that flag:

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    if(properties.$ai_cache_reporting_exclusive = 'true',
       sum(toInt(properties.$ai_cache_read_input_tokens))
         / nullIf(sum(toInt(properties.$ai_input_tokens))
                + sum(toInt(properties.$ai_cache_read_input_tokens))
                + sum(toInt(properties.$ai_cache_creation_input_tokens)), 0),
       sum(toInt(properties.$ai_cache_read_input_tokens))
         / nullIf(sum(toInt(properties.$ai_input_tokens)), 0)
    ) AS cache_hit_rate
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model, properties.$ai_cache_reporting_exclusive
```

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

The `cache_hit_rate` uses the provider-aware formula from the "Cache token
accounting" section above — it branches on `$ai_cache_reporting_exclusive`
so the denominator is correct for both exclusive and inclusive providers
without hardcoding any provider or model names. If a single model mixes
both reporting styles across events (unusual), split by
`$ai_cache_reporting_exclusive` in the GROUP BY instead of `any()`.

Rank and roll up on `total_cost` — summing only the input/output components
drops request and web-search fees and can diverge from the `/llm-analytics`
UI. If `request_cost` or `web_search_cost` are a meaningful share of
`total_cost` for a model, that's a separate optimisation lever (e.g. chattier
provider, tool-heavy generations).

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
    "series": [
      {
        "kind": "EventsNode",
        "event": "$ai_generation",
        "math": "sum",
        "math_property": "$ai_total_cost_usd"
      },
      {
        "kind": "EventsNode",
        "event": "$ai_embedding",
        "math": "sum",
        "math_property": "$ai_total_cost_usd"
      }
    ],
    "trendsFilter": {
      "formula": "A + B",
      "aggregationAxisPrefix": "$",
      "decimalPlaces": 2
    }
  }
}
```

Both series are required — omitting `$ai_embedding` silently drops embedding
spend. If the project demonstrably does not use embeddings (`count()` of
`$ai_embedding` is zero over the relevant window), you can drop series B and
the formula for a simpler insight.

For "cost per user", add a third series with `math: "dau"` and change the
formula to `(A + B) / C`. For breakdowns, add `breakdownFilter` with
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
  "insight": <insight_id>,
  "name": "Daily LLM cost over $100",
  "subscribed_users": [<user_id>],
  "threshold": {
    "configuration": {
      "bounds": {"upper": 100},
      "type": "absolute"
    }
  },
  "condition": {"type": "absolute_value"},
  "config": {"series_index": 0},
  "enabled": true
}
```

The insight must be a single-value trends query (e.g. bold-number daily cost).
`subscribed_users` is required and must contain at least one user id from the
same team. `threshold.configuration.type` is `"absolute"` or `"percentage"`;
`condition.type` is `"absolute_value"`, `"relative_increase"`, or
`"relative_decrease"`. If the MCP tool rejects the payload, run
`posthog:docs-search` for "alerts" to pull the current schema — the
accepted enum values can change with the alerting API.

## Constructing UI links

- **Dashboard**: `https://app.posthog.com/llm-analytics/dashboard`
- **Traces list** (sort by cost): `https://app.posthog.com/llm-analytics/traces`
- **Generations list**: `https://app.posthog.com/llm-analytics/generations`
- **Users list** (per-user cost): `https://app.posthog.com/llm-analytics/users`
- **Single trace**: `https://app.posthog.com/llm-analytics/traces/<trace_id>?timestamp=<url_encoded_iso>`

Always surface a UI link so the user can verify visually.

## Keeping this skill current

Provider reporting behaviour (which tokens are inclusive vs exclusive,
which costs show up where) shifts over time and can differ between SDK
versions for the same provider. To avoid rot:

- Branch on event-level flags (`$ai_cache_reporting_exclusive`,
  `$ai_cost_model_source`) rather than hardcoded provider or model names.
  Those flags are ingestion's resolved answer for the specific event and
  are the right source of truth.
- `$ai_total_cost_usd` is always authoritative for rollups — prefer it
  over summing components, which can drift as new cost categories are
  added.
- For anything not covered here (new cost categories, changes to
  pricing lookup, provider additions), run `posthog:docs-search` for
  "calculating costs" or "llm analytics" first rather than trusting a
  hardcoded rule in this file.
- If you find this skill contradicting the UI, trust the UI and flag
  the skill for an update.

## Tips

- Always set a time range — cost queries without one scan the full events table
- Always include `$ai_embedding` alongside `$ai_generation` when summing cost; embeddings are cheap per-call but add up at scale
- Costs are written at ingestion (see [Calculating LLM costs](https://posthog.com/docs/llm-analytics/calculating-costs)) — if `$ai_total_cost_usd` is missing or zero, read `$ai_cost_model_source` first: `passthrough` means the SDK supplied costs; `custom` means custom token prices; `openrouter` / `manual` mean automatic lookup; missing means the model wasn't matched (unusual custom model, fine-tune). Grep: `countIf(properties.$ai_total_cost_usd IS NULL)` per `(model, source)`
- Custom pricing uses **per-token** prices, not per-million — if a custom-priced model looks ~1M× too expensive or too cheap, that's almost always the bug
- Exclude errored calls from cost totals only when explicitly asked — providers still charge for many error modes, and including them gives the truthful bill
- For per-user totals, exclude rows where `distinct_id = properties.$ai_trace_id` — some SDKs default distinct_id to the trace ID when no user is set
- Cost is additive across `$ai_generation` + `$ai_embedding` events within a trace; summing on `$ai_span` gives zero. `$ai_trace` may carry `$ai_total_cost_usd` from some SDK wrappers — don't include it in rollups or you'll double-count. `$ai_evaluation` events also carry cost but are not part of the stock UI rollups; include them only when the user explicitly wants evaluation spend in the total
- Cache-hit rate depends on `$ai_cache_reporting_exclusive` — branch on the event-level flag rather than on provider or model name. Provider behaviour and SDK versions drift; the flag is ingestion's resolved answer for that specific event
- When answering "why is X expensive?", show the cost **and** the token split — the user almost always wants to know whether to shrink prompts, shrink outputs, or switch models
- Before building a custom dashboard, check whether the stock `/llm-analytics/dashboard` tiles already answer the question — re-creating them is churn
- For large tenants, materialize common cost queries as insights and reuse via `insight-query`; ad-hoc SQL is fine for one-offs but re-running it on every dashboard load is expensive
