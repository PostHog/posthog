# Shared patterns

Reusable recipes and guardrails referenced from every per-type playbook.
Keep this file lean: only patterns that appear in two or more playbooks live here.

## When to use `posthog:execute-sql` instead of structured tools

The structured query tools (`posthog:query-trends`, `posthog:query-funnel`,
`posthog:query-retention`, `posthog:query-paths`, `posthog:query-stickiness`,
`posthog:query-lifecycle`, `posthog:query-trends-actors`) use LLM-curated schemas
(simpler than raw `TrendsQuery` / `FunnelsQuery` / etc. — they strip rendering-only fields)
and their output composes cleanly with `posthog:query-trends-actors`. Prefer them for
anything that fits.

Reach for `posthog:execute-sql` (HogQL) only when the question cannot be expressed by a
structured tool:

- **Ratios across events** — "event A per user per day compared to event B per user per day"
- **Joins with data-warehouse tables** — "events where the person is in a data-warehouse cohort"
- **Custom aggregation** — "p90 of `properties.duration` per day, filtered to logged-in users"

## HogQL quantile template

When you need per-bucket distribution stats — especially with a segment dimension that
box plots can't express as a `breakdownFilter` — use `quantiles()` in HogQL. Used by
[box-plot-playbook.md](./box-plot-playbook.md) steps 3 and 4.

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
ORDER BY day, segment
```

- `toFloat(properties.X)` — event properties are loosely typed; cast explicitly or the
  quantile silently treats them as strings and returns nonsense.
- Report `n` alongside the quantiles — a p75 swing on a small `(day, segment)` cell is
  usually noise (see **interpreting breakdown results**).
- For a single-tail actor query (not per-bucket stats), use `quantile(0.9)(...)` in a
  subquery filter — see `box-plot-playbook.md` §4.

## Property discovery

Before breaking down, discover what's attached. A breakdown on a non-existent property
produces an empty chart that looks like "no data" but really means "wrong property name".

**Event properties** (including custom properties the app sets):

```json
{
  "type": "event",
  "eventName": "<your event>"
}
```

Scopes `posthog:properties-list` to a specific event. By default this excludes core PostHog
properties (`$browser`, `$current_url`, etc.) so app-specific ones surface naturally
(`plan`, `tier`, `feature_area`, `channel`). Set `"includePredefinedProperties": true` if
you want built-ins in the same list.

**Person properties**:

```json
{ "type": "person" }
```

**Finding an event when you don't know its exact name**: `posthog:event-definitions-list`
with no filters enumerates events; search client-side for the one the user meant.

## Breakdown dimensions

Run several breakdowns — you rarely know in advance which dimension reveals the affected
segment. Typical dimensions to try:

- **Standard event context** — `$browser`, `$browser_version`, `$os`, `$device_type`,
  `$screen_width`, `$geoip_country_code`. Always available; a drop concentrated in one
  platform is often a tracking or rendering bug.
- **Feature-flag exposure** — `$feature/<flag_key>` separates exposed vs. control users.
  Highest-signal for post-release investigations.
- **User state** — `is_identified` on the person (anonymous vs authenticated),
  `$is_first_session` on the event (new vs returning), plan / tier on the person.
- **Custom event properties** discovered via the property-discovery recipe above —
  project-specific, often diagnostic.
- **Technical / version** — `app_version`, `$lib_version` for SDK regressions.

## Interpreting breakdown results

Measure "absorbs most of the delta" in **absolute** terms, not percentages. A 50% swing on a
series that's 1% of volume explains only 0.5% of the aggregate delta. Check each series'
volume and absolute contribution before concluding it's the driver — a dramatic movement on
a small series is usually noise.

If no breakdown value isolates the delta, the cause is likely system-wide (bad deploy,
tracking regression, infra issue) rather than segment-specific. Note the negative result
and move on; breakdowns find segment-shaped causes and are silent on system-wide ones.

If you suspect an interaction between two dimensions (e.g., a browser bug that only affects
one country), try a compound breakdown with up to three properties in `breakdowns`.

If the event fires fewer than ~100 times per interval, percentage changes are unreliable —
report absolute numbers alongside percentages.

## Interval zoom (narrowing the anomaly window)

When a daily point looks anomalous, rerun the same query scoped tightly to the suspicious
day(s) with `interval: "hour"`. The shape often answers the hypothesis: a one-hour spike is
an incident; a full-day dip is a broader cause.

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "2026-03-10T00:00:00Z", "date_to": "2026-03-10T23:59:59Z" },
  "interval": "hour",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }]
}
```

Use `interval: "minute"` for even tighter windows (e.g., a 2-hour incident window).

## Actor drilldown

`posthog:query-trends-actors` accepts only a trends source today (`AssistantTrendsQuery`),
not funnels or other insight kinds. Pass the TrendsQuery whose anomalous bucket you want to
drill, plus the selector fields (`day`, `series`, `breakdown`):

```json
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

## Session recordings for affected users

For UI/UX-shaped drops, pull recordings matching the affected window / segment via
`posthog:query-session-recordings-list` — watching a handful is often faster than more
queries:

```json
{
  "kind": "RecordingsQuery",
  "dateRange": { "date_from": "2026-03-10", "date_to": "2026-03-10" },
  "properties": [{ "type": "event", "key": "plan", "operator": "exact", "value": "free" }],
  "limit": 20
}
```

Retrieve individual recordings via `posthog:session-recording-get` with the session ID.

## Error / logs cross-check

Call `posthog:error-tracking-issues-list` and `posthog:query-logs` filtered to the anomaly
window. A correlated error is a candidate, not a conclusion — to confirm, check:

1. **Timing** — does the error's volume spike align with the metric movement?
2. **Plausible mechanism** — would the error actually block / affect the metric's surface?
   A 500 on a submit endpoint can plausibly cause failures; a console warning elsewhere
   usually can't.
3. **User overlap** — do the users hitting the error overlap with the affected segment?

If any check fails, the error is coincidental; note it and move on.
