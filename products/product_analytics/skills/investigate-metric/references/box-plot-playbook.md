# Box plot metrics playbook

For TrendsQuery insights with `trendsFilter.display = "BoxPlot"`. The metric is the
distribution of a numeric `math_property` per bucket (min, p25, median, mean, p75, max),
not a count. Box plots silently drop `breakdownFilter` (it's in
`NON_BREAKDOWN_DISPLAY_TYPES`), so segmentation and tail drilldown route through HogQL.

## 1. Which statistic moved

Read `boxplot_data` per bucket and classify before hypothesizing:

- **Median moved** — behavioral change in the middle of the population.
- **IQR widened** — a new slow / fast segment appeared.
- **IQR narrowed** — a tail was removed (feature gate, rate limit, dependency outage).
- **Outliers changed** — toggle `trendsFilter.excludeBoxPlotOutliers`. If the shift
  disappears, it's outlier-driven; if it persists, the bulk moved.
- **Mean / median diverge** — skew changed; tails are pulling the mean.

Tail-driven and bulk shifts have different next steps.

## 2. Zoom

Rerun at `interval: "hour"` on the anomaly window. A one-hour IQR compression usually
points to a deploy or incident; a sustained shift suggests a broader population or
tracking change.

## 3. Segment

Two options instead of `breakdownFilter`:

**Parallel series** — one `EventsNode` per segment value, filtered via `properties`:

```json
posthog:query-trends
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "trendsFilter": { "display": "BoxPlot" },
  "series": [
    {
      "kind": "EventsNode", "event": "checkout_completed",
      "math": "p75", "math_property": "order_value",
      "properties": [{ "type": "event", "key": "plan", "value": "free", "operator": "exact" }]
    },
    {
      "kind": "EventsNode", "event": "checkout_completed",
      "math": "p75", "math_property": "order_value",
      "properties": [{ "type": "event", "key": "plan", "value": "paid", "operator": "exact" }]
    }
  ]
}
```

**HogQL** — see [shared-patterns.md](./shared-patterns.md#hogql-quantile-template).
Better when the segment has many values. Watch for noisy quartiles on small `n`.

Once a candidate segment looks elevated, **don't conclude yet**. A segment can look
guilty for two very different reasons:

- The segment's measurement changed at the anomaly start (real cause).
- The segment was always elevated, and its share of total volume grew at the
  anomaly start (cohort composition change — same numbers, different fix).

Two cheap checks before concluding:

- **Pre-anomaly baseline.** Run the same per-segment quantiles on a window
  _before_ the anomaly. If the elevated segment was already elevated, it's
  composition not measurement.
- **Cross-tab.** If two dimensions both look elevated (e.g. host + lib_version),
  `GROUP BY` both in HogQL to see whether one is causal or they're correlated.

## 4. Tail actor drilldown

`posthog:query-trends-actors` can't select by percentile. Use HogQL with a quantile
filter:

```sql
SELECT distinct_id, max(toFloat(properties.order_value)) AS max_value
FROM events
WHERE event = 'checkout_completed'
  AND timestamp >= '2026-04-15 00:00:00'
  AND timestamp <  '2026-04-16 00:00:00'
  AND toFloat(properties.order_value) > (
    SELECT quantile(0.9)(toFloat(properties.order_value))
    FROM events
    WHERE event = 'checkout_completed'
      AND timestamp >= '2026-04-15 00:00:00'
      AND timestamp <  '2026-04-16 00:00:00'
  )
GROUP BY distinct_id
ORDER BY max_value DESC
LIMIT 50
```

Mirror with `< quantile(0.1)(...)` for the lower tail. Feed IDs into
`posthog:query-session-recordings-list` for UI-shaped shifts.

## 5. Errors / logs

Did a failure mode truncate the distribution? Timeouts killing the slow tail, a
validation error blocking expensive orders. Confirm timing, plausible mechanism, and
user overlap.

## 6. Cohort composition

Run `posthog:query-lifecycle` on the same event. A distribution shift often reflects a
mix change — an influx of new free-tier users can pull p75 order value down while
no existing user changed behavior.
