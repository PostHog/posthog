# Materializing cost queries as insights, dashboards, and alerts

After ad-hoc queries answer the question, persist them as insights, bundle into
a dashboard, or wire up alerts.

## Save a cost-over-time insight

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

## Add to a dashboard

After saving the insights, use `posthog:dashboard-create` (or `-update`) to
bundle them. The default `/llm-analytics/dashboard` already includes Cost,
Cost per user, and Cost by model tiles — mirror that structure when building
a custom one.

## Alert on a cost threshold

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
