# Funnel metrics playbook

For "conversion fell", "drop-off increased at step X", "signup-to-purchase fell off".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes
(interval zoom, breakdown dimensions, session recordings, error cross-check).

## 1. Confirm which step regressed

`posthog:query-funnel` with the user's steps. Identify the step where conversion dropped.
Compare to a baseline window using `compareFilter: {"compare": true}`.

```json
{
  "kind": "FunnelsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [
    { "kind": "EventsNode", "event": "signed up" },
    { "kind": "EventsNode", "event": "completed onboarding" },
    { "kind": "EventsNode", "event": "first purchase" }
  ],
  "funnelsFilter": { "funnelWindowInterval": 7, "funnelWindowIntervalUnit": "day" }
}
```

## 2. Is it entries or completions?

Run two `posthog:query-trends` calls — one for entries to step N, one for completions of
step N. If entries are steady but completions fell, the problem is at that step. If
entries also fell, the problem is upstream.

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "<event at step N>", "math": "dau" }]
}
```

If a specific day looks anomalous, apply the **interval zoom** pattern from shared-patterns
to get hour-level resolution.

## 3. Who is dropping off?

`posthog:query-trends-actors` only accepts a trends source today (see **actor drilldown**
in shared-patterns). Work around it: run a trends query for users who completed step N-1
but did not complete step N within the funnel window, then drill into the actors of that
trend.

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    {
      "kind": "EventsNode",
      "event": "<event at step N-1>",
      "math": "dau",
      "properties": [
        {
          "type": "hogql",
          "key": "not exists (select 1 from events e2 where e2.person_id = events.person_id and e2.event = '<event at step N>' and e2.timestamp between events.timestamp and events.timestamp + interval 7 day)"
        }
      ]
    }
  ]
}
```

Adjust the `interval 7 day` to match the funnel window, then pass this trend to
`posthog:query-trends-actors`. For a simpler approximation that doesn't need HogQL, run a
trend on step-N-1 completions and one on step-N completions and diff the actor lists.

Apply **breakdown dimensions** from shared-patterns to the trends query to segment the
dropped-out users. For UI/UX drop-offs, pull **session recordings** for those actors.

## 4. Cross-check against errors

Apply the **error / logs cross-check** pattern from shared-patterns. For funnel steps
specifically: filter to the surface where step N lives — a 500 at the submit endpoint can
plausibly cause failures; a console warning elsewhere usually can't.

## 5. What are they doing instead?

`posthog:query-paths` with `endPoint` set to the failing step. Paths that do not reach
the end point show what users do when they bail.

```json
{
  "kind": "PathsQuery",
  "dateRange": { "date_from": "-30d" },
  "pathsFilter": {
    "endPoint": "<event at step N>",
    "includeEventTypes": ["$pageview", "custom_event"],
    "edgeLimit": 50
  }
}
```
