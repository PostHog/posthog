# Shared patterns

Recipes used across playbooks.

## When to reach for HogQL

Use the typed query tools by default. Use `posthog:execute-sql` only when the question
can't be expressed structurally:

- Ratios across different events.
- Joins with data-warehouse tables.
- Custom aggregations like `quantile`, `arrayJoin`, regex extraction.

## HogQL insights

For saved insights with `query.kind === "HogQLQuery"`, the playbook routing is shape-based
rather than kind-based. Read the SQL and pick the closest playbook:

- `count(...) GROUP BY toStartOfDay(...)` or similar count-over-time → trend playbook.
- Multi-step `windowFunnel` or sequential filtering → funnel playbook.
- Cohort-keyed return aggregates → retention playbook.

Run the insight's SQL through `posthog:execute-sql` to get the data, then follow the
chosen playbook's steps using the typed tools where they fit. Drop back to
`execute-sql` for the breakdown / drilldown variants when the original SQL has shape
the typed schema can't express.

## HogQL quantile template

For per-bucket distribution stats with a segment dimension (box plots can't take
`breakdownFilter`).

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    properties.plan         AS segment,
    quantiles(0.25, 0.5, 0.75, 0.9)(toFloat(properties.order_value)) AS q,
    count()                 AS n
FROM events
WHERE event = 'checkout_completed'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, segment
```

- Cast `toFloat(properties.X)` — properties are loose-typed.
- Report `n` alongside quantiles; a p75 swing on small cells is usually noise.

## Property discovery

Use `posthog:read-data-schema` to discover events and properties before filtering or
breaking down. The `query.kind` field selects:

- `events` — list events for fuzzy-matching by name.
- `event_properties` with `event_name` — properties on a specific event.
- `entity_properties` with `entity: "person"` — person properties.
- `event_property_values` with `event_name` + `property_name` — sample values.

## Related-metrics sweep

Before going deep on one metric, run the same anomaly-window query on 2–3 adjacent
metrics — upstream funnel steps, sibling events, total event volume, parent-event
counts. If they all moved together, the cause is broader than the specific metric
(ingestion gap, cohort shift, tracking regression). If only the target metric moved,
the investigation is correctly scoped.

Use when the metric sits inside a larger pipeline (a funnel step, a retention activity
event, a derived rate) and you want to rule out an upstream cause cheaply.

```json
posthog:query-trends
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [
    { "kind": "EventsNode", "event": "$pageview", "math": "total" },
    { "kind": "EventsNode", "event": "user signed up", "math": "total" },
    { "kind": "EventsNode", "event": "first team event ingested", "math": "total" }
  ]
}
```

A single multi-series query is cheaper than three breakdowns and the visual alignment
(or lack of it) answers the question immediately.

## Breakdown dimensions

A few candidate dimensions, roughly in order of signal:

- `$feature/<flag_key>` — highest signal post-release.
- `$browser`, `$os`, `$device_type`, `$geoip_country_code` — for platform / regional issues.
- `app_version`, `$lib_version` — for SDK regressions.
- `is_identified`, `$is_first_session`, plan / tier — for user-state issues.
- Custom event properties from `read-data-schema` — usually most diagnostic.

## Interpreting breakdown results

Rank by **absolute** delta, not %. Pipe through
[`breakdown_attribution.py`](./../scripts/breakdown_attribution.py) — it ranks by
contribution and detects offsetting cases (aggregate flat, segments moved oppositely).

If no breakdown isolates the delta the cause is system-wide (deploy, tracking, infra),
not segment-specific. Try a compound breakdown of up to 3 properties for
interaction effects (e.g. one browser × one country).

If event volume per interval < ~100, percentages are unreliable — report absolutes too.

When a segment looks guilty, check its **pre-anomaly baseline** before concluding:
the segment may have always behaved that way, with its share of volume just growing
at the anomaly start (cohort composition change, not a real regression).

## Interval zoom

When a daily point looks anomalous, rerun the query at `interval: "hour"` scoped to that
day. A one-hour cliff is an incident; a sustained shift is something broader. Use
`interval: "minute"` for tight incident windows.

## Actor drilldown

`posthog:query-trends-actors` only accepts a trends source. The selector fields are `day`,
`series`, and (if breakdown) `breakdown`:

```json
posthog:query-trends-actors
{
  "kind": "InsightActorsQuery",
  "source": {
    "kind": "TrendsQuery",
    "dateRange": { "date_from": "2026-03-10", "date_to": "2026-03-10" },
    "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "dau" }],
    "breakdownFilter": { "breakdowns": [{ "property": "plan", "type": "event" }] }
  },
  "day": "2026-03-10",
  "breakdown": "free"
}
```

## Session recordings

For UI-shaped drops, pull recordings matching the affected segment via
`posthog:query-session-recordings-list`. Watching three or four is often faster than
running more queries. Fetch individual ones with `posthog:session-recording-get`.

## Error / logs cross-check

Run `posthog:error-tracking-issues-list` and `posthog:query-logs` for the anomaly window.
A correlated error is a candidate, not a conclusion — confirm three things:

1. **Timing** — error volume aligns with the metric movement.
2. **Plausible mechanism** — the error actually affects the metric's surface (a 500 on a
   submit endpoint can; a console warning usually can't).
3. **User overlap** — affected users overlap with users hitting the error.

If any check fails, note the error as coincidental and move on.
