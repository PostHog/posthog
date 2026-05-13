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

## Core rules

Three rules cover most of what goes wrong:

- **Sum `$ai_total_cost_usd` for rollups, never the components.** Components drop
  request and web-search fees. The UI's cost cells sum `$ai_total_cost_usd`
  over `event IN ('$ai_generation', '$ai_embedding')`; mirror that. Full
  schema and rationale in [cost properties](./references/cost-properties.md).
- **Always include both `$ai_generation` and `$ai_embedding`** in cost queries
  unless the project demonstrably does not use embeddings — missing them silently
  under-counts. `$ai_trace` and `$ai_span` carry no rollup cost; some SDK
  wrappers duplicate `$ai_total_cost_usd` onto `$ai_trace` so don't include
  it in rollups or you'll double-count.
- **Always set a time range.** Cost queries without one scan the full events table.

`$ai_total_cost_usd` is set at ingestion via one of three paths (passthrough,
custom pricing, automatic lookup). When a cost looks wrong, read
`$ai_cost_model_source` first — see [cost sources](./references/cost-sources.md)
for the precedence rules and a diagnostic query.

Cache-hit math depends on whether the provider reports cache tokens inclusively
or exclusively of `$ai_input_tokens`. Always branch on the per-event
`$ai_cache_reporting_exclusive` flag, never on provider name — see
[cache accounting](./references/cache-accounting.md) for the exclusive-vs-inclusive
formula.

`distinct_id` is the canonical user dimension. Customers often attach custom
properties (`feature`, `tenant_id`, `workflow_name`) — discover them with
`posthog:read-data-schema` before grouping. Don't guess names.

## Workflow: total spend in a window

```sql
posthog:execute-sql
SELECT round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost_usd
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 30 DAY
```

## Workflow: cost breakdowns

Every cost question is a variation of the same template — group by a dimension,
aggregate `$ai_total_cost_usd`. See [breakdown patterns](./references/breakdown-patterns.md)
for ready-to-run recipes:

- Cost over time (daily)
- Cost by model
- Cost by user (top spenders)
- Cost by trace (top expensive traces)
- Cost by custom dimension
- Cost-per-call distribution
- Input vs output vs cache economics

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
prompts, a new model, or a change in cache-hit rate. Work through them in
order — see [regression debugging](./references/regression-debugging.md) for
the 5-step playbook.

## Workflow: materialize as an insight, dashboard, or alert

After ad-hoc queries answer the question, persist them as insights, bundle
into a dashboard, or wire up alerts. See [materializing](./references/materializing.md)
for ready-to-run JSON for `posthog:insight-create`, `posthog:dashboard-create`,
and `posthog:alert-create`.

## Constructing UI links

- **Dashboard**: `https://app.posthog.com/llm-analytics/dashboard`
- **Traces list** (sort by cost): `https://app.posthog.com/llm-analytics/traces`
- **Generations list**: `https://app.posthog.com/llm-analytics/generations`
- **Users list** (per-user cost): `https://app.posthog.com/llm-analytics/users`
- **Single trace**: `https://app.posthog.com/llm-analytics/traces/<trace_id>?timestamp=<url_encoded_iso>`

Always surface a UI link so the user can verify visually.

## Keeping this skill current

Provider reporting behavior (which tokens are inclusive vs exclusive,
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
- Cache-hit rate depends on `$ai_cache_reporting_exclusive` — branch on the event-level flag rather than on provider or model name. Provider behavior and SDK versions drift; the flag is ingestion's resolved answer for that specific event
- When answering "why is X expensive?", show the cost **and** the token split — the user almost always wants to know whether to shrink prompts, shrink outputs, or switch models
- Before building a custom dashboard, check whether the stock `/llm-analytics/dashboard` tiles already answer the question — re-creating them is churn
- For large tenants, materialize common cost queries as insights and reuse via `insight-query`; ad-hoc SQL is fine for one-offs but re-running it on every dashboard load is expensive

## References

- [cost properties](./references/cost-properties.md) — full property schema, total-cost rationale, event-set rules
- [cost sources](./references/cost-sources.md) — how costs get set at ingestion plus a diagnostic query
- [cache accounting](./references/cache-accounting.md) — exclusive vs inclusive providers, cache-hit-rate formula
- [breakdown patterns](./references/breakdown-patterns.md) — SQL recipes for every common breakdown
- [regression debugging](./references/regression-debugging.md) — 5-step playbook for cost spikes
- [materializing](./references/materializing.md) — insight, dashboard, and alert JSON
