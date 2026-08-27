---
name: choosing-chart-display
description: >
  Chart type and display settings for a readable insight: `display`, legend, series
  count, secondary axis, stacking. Use when creating or updating a trends or SQL insight
  (`insight-create`, `insight-update`), or when a chart is unreadable, cluttered, or the
  wrong type. Units: `formatting-insight-axes`. Line vs slope: `choosing-trend-or-slope-view`.
---

# Choosing a chart display

Defaults are tuned for the simplest case, not the chart you are building.

## Pick one chart type

| The result is...                       | Use                                                |
| -------------------------------------- | -------------------------------------------------- |
| A measure over time                    | `ActionsLineGraph` (the trends default)            |
| A measure over time, part-of-whole     | `ActionsAreaGraph` or `ActionsStackedBar`          |
| Categories compared against each other | `ActionsBar` (SQL) / `ActionsBarValue` (trends)    |
| Proportions of one total, few slices   | `ActionsPie`                                       |
| One number                             | `BoldNumber`, or trends `Metric` for a change pill |
| Two measures, one point per row        | `ScatterPlot`                                      |
| Rows to scan or copy                   | `ActionsTable`                                     |

Two traps:

- SQL insights render as `ActionsTable` when `display` is omitted, so a time series left at the default is a wall of rows.
- Trends `ActionsBar` is a time-series bar chart, one bar per interval. "Top N countries" wants `ActionsBarValue`.

## Mix bar and line when it adds meaning

`auto` for `yAxis[].settings.display.displayType` suits most charts. Two mixes read well:

- A line that annotates the bars in the same unit: rolling average, target, cumulative.
- A series in a different unit or scale, pinned to the secondary axis. Label both axes (`leftYAxisSettings.label`, `rightYAxisSettings.label`).

```json
{ "column": "conversion_rate", "settings": { "display": { "displayType": "line", "yAxisPosition": "right" } } }
```

Unrelated measures sharing one axis read better as separate insights.

## Turn the legend on for more than one series

SQL charts default to `showLegend: false`, leaving a multi-series chart readable only by hovering.
Set `showLegend: true` whenever several `yAxis` columns or a `seriesBreakdownColumn` render.
This is the most common miss, because nothing about writing the query prompts it.

## Cap the series count

Past about six series a line chart reads as spaghetti.
Keep a top N with an `Other` row, split into several insights, or switch to `ActionsTable`.

## Settings that usually hurt

- `showValuesOnSeries`: fine on a few bars, unreadable on a dense time series.
- `trendLine`: only when the trend is the point.
- Log scale (`leftYAxisSettings.scale`, `trendsFilter.yAxisScaleType`): only for series spanning orders of magnitude.
- `stackBars100`: hides absolute movement, so pair it with a volume chart.
- Bar charts need `leftYAxisSettings.startAtZero`; a truncated bar axis misstates the ratio between bars.

## Field locations

| Decision        | Trends (`trendsFilter`)           | SQL (`chartSettings`)                    |
| --------------- | --------------------------------- | ---------------------------------------- |
| Chart type      | `display`                         | `display` (on the node)                  |
| Legend          | `showLegend`                      | `showLegend`                             |
| Second y-axis   | `showMultipleYAxes`               | `yAxis[].settings.display.yAxisPosition` |
| Per-series type | not available, one type per chart | `yAxis[].settings.display.displayType`   |
| Log scale       | `yAxisScaleType`                  | `leftYAxisSettings.scale`                |
| Axis label      | `xAxisLabel` / `yAxisLabel`       | `xAxisLabel` / `leftYAxisSettings.label` |
