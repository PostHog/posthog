# Trend metrics playbook

For any count-over-time metric — "DAU dropped", "revenue spiked", "clicks fell",
"sessions fell after the release".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes
(interval zoom, property discovery, breakdown dimensions, actor drilldown, session
recordings, error cross-check).

## 1. Zoom in on the anomaly window

Apply the **interval zoom** pattern from shared-patterns. Rerun `posthog:query-trends`
with the user's metric, `interval: "hour"`, and a tight `dateRange` around the suspicious
day(s). Hourly resolution reveals the shape of the anomaly: a narrow spike / cliff points
to a specific incident, deploy, or cron job; a sustained shift points to broader causes
(campaign, cohort change, tracking regression).

## 2. Break down the trend

Run several breakdowns to see if one segment is driving the change. Rerun
`posthog:query-trends` with different `breakdownFilter.breakdowns` values.

Discover properties attached to the metric's event first (see **property discovery** in
shared-patterns), then try the dimensions from the **breakdown dimensions** menu —
standard event context, feature-flag exposure, user state, custom event properties,
technical / version.

Apply the **interpreting breakdown results** guidance: check absolute contribution (a
dramatic % swing on a small series is usually noise); if no single dimension isolates the
delta, the cause is likely system-wide (bad deploy, tracking regression, infra).

Example call:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "dau" }],
  "breakdownFilter": {
    "breakdowns": [{ "property": "plan", "type": "event" }],
    "breakdown_limit": 10
  }
}
```

## 3. Identify the affected users

Apply the **actor drilldown** pattern. Run `posthog:query-trends-actors` on the anomalous
bucket (specific day/hour, or the breakdown value that moved). Inspect returned persons'
properties for common threads.

For UI/UX-shaped drops, also pull **session recordings** for the same window / segment
via `posthog:query-session-recordings-list`.

## 4. Cross-check against errors / logs

Apply the **error / logs cross-check** pattern. An aligned error spike is a candidate,
not a conclusion — confirm with the three checks (timing, plausible mechanism, user
overlap) from shared-patterns.

## 5. Check for a cohort-composition change

`posthog:query-lifecycle` on the same metric:

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "$pageview" }]
}
```

If the drop is concentrated in one lifecycle status (new users didn't arrive, dormant
users didn't resurrect), that reframes the investigation — the metric may be fine
behaviorally while the _mix_ of users changed.
