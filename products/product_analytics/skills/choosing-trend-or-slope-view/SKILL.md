---
name: choosing-trend-or-slope-view
description: >
  Clarify how to visualize change over a time range before building a trend.
  Use whenever the user asks how much something changed, grew, dropped,
  improved, or regressed between two points or periods — "how much did X change
  from A to B", "before vs after", "start vs end", "week over week", "compare
  this month to last", "change over time" — or mentions a "slope chart" /
  "slopegraph". Two readings of "change" need different charts: the whole trend
  (a line, every interval) versus just the two endpoints (a slope, start vs
  end). Ask which they want, then render it. Not for choosing a saved insight
  ChartDisplayType in the insight editor.
---

# Choosing a trend line vs a slope view

"How did X change between A and B?" is ambiguous. Two charts answer two different
questions, so **clarify before you build** unless the user already named one:

- **Change over time (line)** — the value at every interval across the range.
  Shows the *path*: dips, spikes, when it moved. This is the default trend.
- **Start vs end (slope)** — only the first and last point, one line per series
  connecting them. Shows the *net change* and, across many series, which rose,
  which fell, and any rank flips — without the noise of the path between.

When the request could be either, ask a short either/or, e.g.:

> Do you want to see how it moved across the whole period (a line chart), or just
> the change from the start to the end (a slope chart)?

If the user clearly wants one — "just tell me how much it grew start to end" → slope;
"show me the trend / when did it spike" → line — skip the question and build it.

## How to render each

Both come from the **same** `TrendsQuery` over the same date range — the slope is
that series collapsed to its first and last point, not a different query.

### Change over time → line

Default trends behavior. Create or run a `TrendsQuery` and leave
`trendsFilter.display` as `ActionsLineGraph` (the default, "change over time"):

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
  "dateRange": { "date_from": "2025-01-01", "date_to": "2025-03-31" },
  "trendsFilter": { "display": "ActionsLineGraph" }
}
```

### Start vs end → slope

Run the trend with `posthog:query-trends`. The result card Max renders has a
**Line / Bar / Slope** view toggle — switch it to **Slope** to show each series as
a single line from its first to its last point, with the per-series change in the
legend. Tell the user they can flip to the Slope view on the result.

The slope view is best for a clean before→after comparison, especially with several
series/categories whose relative movement matters. Pick a date range whose two ends
are the points you want compared (the slope uses the first and last interval).

## Important limits

- **Slope is a view, not a saved insight type.** It lives on Max's inline trends
  result card (the `query-trends` visualizer). A *saved* insight has no slope
  display — `SlopeChart` is not a `ChartDisplayType`, so `posthog:insight-create`
  with a slope display is not available. If the user wants a saved/dashboard chart,
  save the line and offer the slope as the inline view, or note the limitation.
- For period-over-period on a single series (this month vs last), a line with
  `compareFilter: { "compare": true }` overlays the two periods; a slope is the
  better fit when comparing the endpoints of **many** series at once.
