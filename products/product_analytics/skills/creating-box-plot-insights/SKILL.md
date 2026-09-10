---
name: creating-box-plot-insights
description: >-
  Creates product analytics or SQL-backed box plot insights in PostHog. Use when a user asks to create, build, or save a box plot, visualize a numeric distribution, compare quartiles or medians across dates or groups, or turn SQL results into a box plot. Chooses between a standard Trends box plot and a SQL insight, validates the distribution data, saves the insight, and verifies it.
---

# Creating box plot insights

Box plots need distribution data, not an already-aggregated average or total. Choose the simplest query type that can express the user's question.

## Choose the query type

Use a **standard product analytics box plot** when all of these are true:

- The source is an event, action, or warehouse table supported by Trends.
- One numeric property contains the values to distribute.
- The user wants the distribution over a normal time interval.

Use a **SQL box plot** when the user needs custom grouping, joins, derived values, or bespoke SQL. Read `querying-posthog-data` before writing HogQL, then use [references/sql-examples.md](references/sql-examples.md) as a starting point.

Do not use SQL only to reproduce a standard Trends query.

## Standard product analytics box plot

1. Identify the event or action and its numeric property. Confirm the property is numeric before saving.
2. Build an `InsightVizNode` whose source is a `TrendsQuery`:
   - Set the series event or action.
   - Set `math_property` to the numeric property.
   - Set `trendsFilter.display` to `BoxPlot`.
   - Choose the date range and interval that match the question.
3. Run the query with `posthog:query-trends`.
4. If it returns distribution rows, save it with `posthog:insight-create`.
5. Read it back with `posthog:insight-get` and confirm the property, interval, and display.

A box plot without a numeric `math_property` is invalid. Do not substitute event counts unless counts are the values the user wants to distribute.

## SQL box plot

The SQL must return one pre-aggregated row for each X-axis and series pair. Calculate the summary in the database. Never calculate percentiles from the limited result rows in the client.

Required numeric roles:

- minimum
- 25th percentile
- median
- mean
- 75th percentile
- maximum

The easiest result shape uses these aliases:

```text
x, series, min, p25, median, mean, p75, max
```

`x` and `series` are optional:

- Set `xAxisColumn` to `null` for one overall distribution or one box per series.
- Set `seriesColumn` to `null` for one series.

Validate the HogQL with `posthog:execute-sql` before saving. Check that:

- Every required statistic is numeric.
- `min <= p25 <= median <= p75 <= max` for every row.
- The mean is between the minimum and maximum.
- Each X-axis and series pair appears once.
- There are at most 200 series and 10,000 X-axis by series cells.

Then save this shape with `posthog:insight-create`:

```json
{
  "query": {
    "kind": "DataVisualizationNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "<validated HogQL>"
    },
    "display": "BoxPlot",
    "chartSettings": {
      "boxPlot": {
        "xAxisColumn": "x",
        "seriesColumn": "series",
        "minColumn": "min",
        "p25Column": "p25",
        "medianColumn": "median",
        "meanColumn": "mean",
        "p75Column": "p75",
        "maxColumn": "max",
        "excludeOutliers": true
      }
    }
  }
}
```

Use the actual aliases when the query uses different names. Do not map the six statistics as six Y-axis series.

## Verify the saved insight

1. Read the saved insight with `posthog:insight-get`.
2. Run it with `posthog:insight-query`.
3. Confirm the result still has the expected columns and one row per box.
4. Report the insight link, the numeric value being distributed, and the grouping choices.

If an individual row has a missing or invalid summary, PostHog omits that box while keeping valid boxes visible. Fix the SQL when omitted boxes are not expected.

## Related skills

- `querying-posthog-data` - required before authoring or changing the HogQL for a SQL box plot.
- `formatting-insight-axes` - use when the value axis needs currency, duration, percentage, or other formatting.
- `building-a-dashboard` - use when the box plot should be placed with other insights on a dashboard.
