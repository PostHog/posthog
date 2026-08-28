List the persons behind one step of a funnel insight — either those who converted through it or those who dropped off at it.

Pair this with `query-funnel`: first run the funnel query to read the per-step counts, then call this tool with the **same** funnel query as `source`. There are two mutually exclusive modes, and the selectors you use must match the source funnel's `funnelsFilter.funnelVizType`.

## Step mode (the default — source `funnelVizType: "steps"`)

Use `funnelStep` to pick a step. The **sign** picks the direction:

- **Positive** `funnelStep` lists actors who **converted through** that step.
- **Negative** `funnelStep` lists actors who **dropped off** at that step.

Steps are **1-based**. Examples for a 3-step funnel:

- `funnelStep: 1` — entered the funnel (reached step 1).
- `funnelStep: 2` — converted through step 2.
- `funnelStep: -2` — dropped off at step 2 (reached step 1 but not step 2).
- `funnelStep: 3` — converted through the whole funnel.
- `funnelStep: -3` — dropped off at step 3.

You cannot drop off at the entry step, so the smallest negative value is `-2`. To list every person at each step, call this tool once per `(step, direction)` you care about — a single call returns one cohort, not all steps.

- `funnelStepBreakdown` (optional): scope to one breakdown series. Pass the breakdown value(s) from the matching `query-funnel` result row verbatim (an array, e.g. `["Chrome"]`). Omit for the baseline (non-breakdown) series.

## Trends-dropoff mode (source `funnelVizType: "trends"`)

For a funnel-trends (conversion-over-time) insight, drill into one point on the chart:

- `funnelTrendsDropOff`: `true` lists actors who dropped off, `false` lists those who converted.
- `funnelTrendsEntrancePeriodStart`: the entrance period as a `YYYY-MM-DD HH:mm:ss` string (e.g. `'2024-01-15 00:00:00'`), taken from the point the user is asking about.

Use these two together. Do not mix them with `funnelStep`.

> The funnel `time_to_convert` viz type has no persons drilldown — this tool does not support it.

## Paging

- `limit`: how many persons to return in one page. Defaults to 100, and anything above 1000 is clamped to 1000.
- `offset`: how many persons to skip before the returned page. Defaults to 0.

## Response

Each returned row contains `distinct_id`, `email`, and `name`, plus a `recordings` column when `includeRecordings` is set (default `true`).

The response also reports `limit`, `offset`, and `hasMore`. When `hasMore` is `true` there are more people at the step — call again with `offset` raised by `limit` to read the next page, and repeat until `hasMore` is `false`.

## Guidance

- Keep the `source` funnel query identical to the one whose step the user is asking about — the series order, date range, conversion window, and filters all determine who converts at each step.
- Make sure the mode matches the source's `funnelVizType`: `funnelStep` needs `"steps"` (the default), `funnelTrendsDropOff` needs `"trends"`. Mixing them returns wrong or empty results.
- To read every person at a step, page with `offset` rather than raising `limit` past 1000, and keep `source` and the step selectors identical across pages so rows don't repeat or go missing.
- When you only need a sample, one page is enough — tighten the source (date range, filters) instead of paging through everyone.
