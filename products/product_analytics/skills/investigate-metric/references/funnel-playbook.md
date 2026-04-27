# Funnel metrics playbook

For "conversion fell", "drop-off increased at step X", "signup-to-purchase fell off".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes
(interval zoom, breakdown dimensions, session recordings, error cross-check).

## 1. Confirm which step regressed

`posthog:query-funnel` with the user's steps. Identify the step where conversion dropped.
`FunnelsQuery` does not support `compareFilter` — run the funnel for two date ranges
(anomaly window and a baseline window of equal length just before it) and compare results.

Anomaly window:

```json
{
  "kind": "FunnelsQuery",
  "dateRange": { "date_from": "-7d" },
  "series": [
    { "kind": "EventsNode", "event": "signed up" },
    { "kind": "EventsNode", "event": "completed onboarding" },
    { "kind": "EventsNode", "event": "first purchase" }
  ],
  "funnelsFilter": { "funnelWindowInterval": 7, "funnelWindowIntervalUnit": "day" }
}
```

Then rerun with `"dateRange": { "date_from": "-14d", "date_to": "-7d" }` for the baseline.

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
in shared-patterns). To find who dropped off, run two trends queries — one on step N-1
completions, one on step N completions — scoped to the same window:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-7d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "<event at step N-1>", "math": "dau" }]
}
```

Then run `posthog:query-trends-actors` on the step N-1 trend to get the actor list.
Compare with the actor list from a similar trends query on step N — users present in
the first list but not the second are the drop-offs.

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
