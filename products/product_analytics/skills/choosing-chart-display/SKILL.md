---
name: choosing-chart-display
description: >
  Pick the chart type and display settings so an insight is readable: `display` /
  `ChartDisplayType`, legend, series count, secondary axis, stacking, value labels.
  Use when creating or updating an insight (`insight-create`, `insight-update`) for
  TrendsQuery or SQL (`DataVisualizationNode`) insights, or when a chart is called
  unreadable, cluttered, spaghetti, or the wrong chart type. For y-axis units see
  `formatting-insight-axes`; for line-vs-slope see `choosing-trend-or-slope-view`.
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

## Do not mix bar and line series

One chart, one series type. Leave `yAxis[].settings.display.displayType` at `auto`.

The only exception: a series on a different scale or unit, pinned to the secondary axis.

```json
{ "column": "conversion_rate", "settings": { "display": { "displayType": "line", "yAxisPosition": "right" } } }
```

Label both axes when you do (`leftYAxisSettings.label`, `rightYAxisSettings.label`).
Series sharing a unit share one type; unrelated measures belong in separate insights.

## Turn the legend on for more than one series

SQL charts default to `showLegend: false`, leaving a multi-series chart readable only by hovering.
Set `showLegend: true` whenever several `yAxis` columns or a `seriesBreakdownColumn` render.
This is the most common miss, because nothing about writing the query prompts it.

## Cap the series count

Past about six series a line chart reads as spaghetti.
Keep a top N with an `Other` row, split into several insights, or switch to `ActionsTable`.

## Settings that usually hurt

- `showValuesOnSeries` — fine on a few bars, unreadable on a dense time series.
- `trendLine` — only when the trend is the point.
- Log scale (`leftYAxisSettings.scale`, `trendsFilter.yAxisScaleType`) — only for series spanning orders of magnitude.
- `stackBars100` — hides absolute movement, so pair it with a volume chart.
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
