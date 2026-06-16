# Lifecycle metrics playbook

For "new users fell", "returning users crashed", "resurrecting stopped coming back".

## 1. Identify which status moved

Run `posthog:query-lifecycle` with the user's metric. Read which of new / returning /
resurrecting / dormant changed.

## 2. Segment

`AssistantLifecycleQuery` doesn't support `breakdownFilter`. To compare segments, run
`posthog:query-lifecycle` once per segment with `properties` filters on the series, or
focus on a single status with `lifecycleFilter.toggledLifecycles: ["new"]` /
`["returning"]`.

```json
posthog:query-lifecycle
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

## 3. Diagnose by status

- **New-user drop** — find the project's first-session event via `read-data-schema`
  (`$session_start`, `$pageview`, or a signup event), then run `posthog:query-paths`
  from there to see where onboarding loses people.
- **Returning-user drop** — `posthog:query-trends` on the cohort's key engagement events.
  Use interval zoom + actor drilldown if a specific day stands out.
- **Resurrecting drop** — usually external. Re-check annotations and re-engagement
  campaign / email events.
