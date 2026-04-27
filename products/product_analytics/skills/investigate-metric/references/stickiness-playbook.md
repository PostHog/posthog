# Stickiness metrics playbook

For "DAU/MAU ratio dropped", "sessions per week fell", "engagement decayed".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes.

## 1. Who got less sticky?

`AssistantStickinessQuery` does **not** support `breakdownFilter`. To compare segments,
run `posthog:query-stickiness` once per segment with property filters on the series.

```json
{
  "kind": "StickinessQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "properties": [{ "type": "person", "key": "plan", "value": "pro", "operator": "exact" }]
    }
  ]
}
```

Rerun with `"value": "free"` (or other segment values) and compare results side by side.
Use the **breakdown dimensions** menu from shared-patterns for candidate segments to try.

## 2. Identify the affected users

To drill into actors for the low-stickiness segment, run `posthog:query-trends` on a key
engagement event filtered to that segment, then apply the **actor drilldown** pattern
from shared-patterns on that trend. Pull **session recordings** for a few of those users
to see how they're actually using the product.

## 3. Compare engagement events between sticky and non-sticky cohorts

Once you have a sticky cohort (high stickiness) and a non-sticky cohort (low stickiness) —
via existing cohorts, ad-hoc filters, or the segment split from step 1 — run
`posthog:query-trends` on candidate core events scoped to each:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "candidate_core_event", "math": "dau" }],
  "properties": [{ "type": "cohort", "key": "id", "value": "<sticky_cohort_id>", "operator": "in" }]
}
```

Rerun with the non-sticky cohort's filter. Events where the two series diverge sharply
are the ones that drive stickiness.
