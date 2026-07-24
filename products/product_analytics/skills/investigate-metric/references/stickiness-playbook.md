# Stickiness metrics playbook

For "DAU/MAU dropped", "sessions per week fell", "engagement decayed".

## 1. Segment

`AssistantStickinessQuery` doesn't support `breakdownFilter`. Run
`posthog:query-stickiness` once per segment with property filters on the series, and
compare side-by-side.

```json
posthog:query-stickiness
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

## 2. Drill into the low-stickiness segment

Run `posthog:query-trends` on a key engagement event filtered to that segment, then
`posthog:query-trends-actors` on the trend. Pull recordings for a handful.

## 3. What sticky users do that non-sticky users don't

With a sticky and a non-sticky cohort, run `posthog:query-trends` on candidate core
events scoped to each (filter via `properties` cohort filter). Events where the two
diverge are the ones driving stickiness.
