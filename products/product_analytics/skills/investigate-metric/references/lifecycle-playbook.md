# Lifecycle metrics playbook

For "new user acquisition fell", "returning users crashed",
"resurrecting users stopped coming back".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes.

## 1. Start with lifecycle itself

`posthog:query-lifecycle` is already the primary tool for this metric type. Run it with
the user's metric to identify which lifecycle status (new, returning, resurrecting,
dormant) moved.

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }]
}
```

## 2. Segment the moved status

`AssistantLifecycleQuery` does **not** support `breakdownFilter`. To isolate a segment,
run `posthog:query-lifecycle` once per segment with property filters on the series:

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "properties": [{ "type": "event", "key": "$geoip_country_code", "value": "US", "operator": "exact" }]
    }
  ]
}
```

Alternatively, focus on a specific status with `lifecycleFilter.toggledLifecycles`, e.g.
`["new"]` or `["returning"]`.

Use the **breakdown dimensions** menu from shared-patterns for candidate segments to try.

## 3. Diagnose based on which status moved

### New-user drop

Identify the canonical first-session event for the project first — call
`posthog:event-definitions-list` and look for `$session_start`, `$pageview`, or a
product-specific signup event. Then run `posthog:query-paths` from that event to see
where new users fall off in onboarding.

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "pathsFilter": {
    "startPoint": "<first-session event name from event-definitions-list>",
    "includeEventTypes": ["$pageview", "custom_event"],
    "edgeLimit": 50
  }
}
```

### Returning-user drop

`posthog:query-trends` on the affected cohort's key engagement events — which activity
fell? Apply the **interval zoom** pattern from shared-patterns if a specific day stands
out. Follow up with the **actor drilldown** pattern to see who the affected returning
users are.

### Resurrecting drop

Usually an external cause. Compare marketing / re-engagement campaign annotations in the
window (they were already checked in Step 2.3 — revisit them here with a resurrecting-
user lens). If no campaign is winding down, check if re-engagement emails / pushes are
still firing via the event stream.
