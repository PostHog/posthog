---
name: choosing-chart-display
description: >
  Pick the chart type and display settings for an insight so it is actually readable:
  the `display` / `ChartDisplayType` choice plus legend, series count, secondary axis,
  stacking, and value labels. Use whenever creating or updating an insight with
  `insight-create` or `insight-update`, for both TrendsQuery (`trendsFilter`) and SQL
  insights (`DataVisualizationNode`, `chartSettings`), or when the user says a chart is
  "unreadable", "cluttered", "spaghetti", "hard to read", "the wrong chart type", or
  asks for a bar / line / pie / stacked / area / scatter chart, a second y-axis, or a
  legend. Covers when NOT to mix bar and line series, how many series one chart can
  carry, and which settings need turning on explicitly because they default to off. For
  y-axis units and number formatting use `formatting-insight-axes`; for the
  line-vs-slope question use `choosing-trend-or-slope-view`.
---

# Choosing a chart display

A query that returns the right numbers still fails if the chart is unreadable.
Pick the display deliberately.
Most defaults are tuned for the simplest case, not for the chart you are actually building.

## 1. Pick one chart type

| The result is...                          | Use                                                     |
| ----------------------------------------- | ------------------------------------------------------- |
| A measure over time                       | `ActionsLineGraph` (the trends default)                 |
| A measure over time, part-of-whole        | `ActionsAreaGraph` or `ActionsStackedBar`               |
| Categories compared against each other    | `ActionsBar` (SQL) / `ActionsBarValue` (trends)         |
| Proportions of a single total, few slices | `ActionsPie`                                            |
| One number                                | `BoldNumber`, or `Metric` for trends with a change pill |
| Two measures related, one point per row   | `ScatterPlot`                                           |
| Rows a reader needs to scan or copy       | `ActionsTable`                                          |

Two traps:

- **SQL insights default to `ActionsTable` when `display` is omitted.**
  A time series left at the default renders as a wall of rows.
  Set `display` explicitly.
- **Trends `ActionsBar` is a time-series bar chart**, one bar per interval.
  For "top N countries" you want `ActionsBarValue`, which bars the totals.

## 2. Do not mix bar and line series

One chart, one series type.
The per-series override (`chartSettings.yAxis[].settings.display.displayType`) defaults to `auto`, which follows the chart-level `display`.
Leave it there.

The single case that justifies a mix:
one series is on a genuinely different scale or unit, and you pin it to the secondary axis.

```json
{
  "yAxis": [
    { "column": "signups", "settings": { "display": { "displayType": "bar", "yAxisPosition": "left" } } },
    { "column": "conversion_rate", "settings": { "display": { "displayType": "line", "yAxisPosition": "right" } } }
  ],
  "leftYAxisSettings": { "label": "Signups" },
  "rightYAxisSettings": { "label": "Conversion rate" },
  "showLegend": true
}
```

If the series share a unit, use one type.
If they are unrelated, use two insights.
A bar/line mix on a single shared axis is noise: the reader cannot compare across shapes, and nothing in the chart explains why they differ.

Whenever you use a secondary axis, label both axes.
Without `leftYAxisSettings.label` and `rightYAxisSettings.label` the reader cannot tell which series reads against which scale.

## 3. Turn the legend on when more than one series renders

SQL charts default to `showLegend: false`.
A multi-series chart without a legend is only decipherable by hovering each line.

Set `showLegend: true` whenever the chart renders more than one series.
That means either several `yAxis` columns, or a `seriesBreakdownColumn`, which splits one column into many.
A single unbroken series does not need one.

This is the most common readability miss, because nothing about writing the query prompts you to think about it.

## 4. Cap the series count

Six series on a line chart is about the limit.
Past that the colors stop being distinguishable and it reads as spaghetti.

When a breakdown returns more:

- Rank in SQL and keep the top N, folding the rest into an `Other` row, or
- Split into several insights along a meaningful cut, or
- Switch to `ActionsTable` if the reader genuinely needs every row.

Do not solve it by shrinking the chart or leaning on the tooltip.

## 5. Settings that usually make things worse

- `showValuesOnSeries` is fine for a handful of bars and unreadable on a dense time series where every point gets a label.
  Leave it off for time series.
- `trendLine` earns its place only when the trend is the point.
  On a series that is already visibly trending it adds a line that says nothing new.
- Logarithmic scale (`leftYAxisSettings.scale: "logarithmic"`, or `trendsFilter.yAxisScaleType: "log10"`) suits series that genuinely span orders of magnitude.
  Otherwise it flattens the change the chart exists to show.
- `stackBars100` suits parts that really do sum to a meaningful whole.
  It hides absolute movement, so pair it with a volume chart when that matters.

## 6. Axis baselines

Bar charts must start at zero.
A truncated bar axis misstates the ratio between bars, which is the whole point of bars.
Set `leftYAxisSettings.startAtZero: true` where the data allows.

Line charts may start off zero when the interesting variation sits in a small band high above it.
Say so in the insight description when they do.

## 7. Field locations

The same decisions live in different places per insight kind:

| Decision        | TrendsQuery (`trendsFilter`)      | SQL (`chartSettings`)                      |
| --------------- | --------------------------------- | ------------------------------------------ |
| Chart type      | `display`                         | `display` (on the `DataVisualizationNode`) |
| Legend          | `showLegend`                      | `showLegend`                               |
| Value labels    | `showValuesOnSeries`              | `showValuesOnSeries`                       |
| Second y-axis   | `showMultipleYAxes`               | `yAxis[].settings.display.yAxisPosition`   |
| Per-series type | not available, one type per chart | `yAxis[].settings.display.displayType`     |
| Log scale       | `yAxisScaleType`                  | `leftYAxisSettings.scale`                  |
| Axis label      | `xAxisLabel` / `yAxisLabel`       | `xAxisLabel` / `leftYAxisSettings.label`   |

Units and number formatting are a separate decision.
See `formatting-insight-axes`.
