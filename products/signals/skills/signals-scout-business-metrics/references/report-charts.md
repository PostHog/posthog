# Supporting charts

Every authored report carries three charts, so the reader sees the move and its driver next to the sentence that names them.
The harness prompt's _Attaching charts_ section carries the chart contract (fields, the query-you-ran rule, pinned windows, named axes, placement, what an edit replaces); this file gives only the three node shapes for this scout and the matching notebook cells.

Two things specific to this scout:

- The incremental read covers 3 periods, so when you author, run the full-window series query once for chart 1 (the first-fill SQL with the window pinned) and stamp it as this run's fill.
- A SQL chart (`DataVisualizationNode`) draws in the inbox but not in a Slack delivery, so the summary's prose must carry the numbers on its own.

The examples below are daily.
For a weekly, monthly or quarterly measure, the series window is the 13 (or 9) closed periods the lens read, the x axis is the period start (`toStartOfMonth(...)`), and chart 2 compares the latest closed period with the average of the base periods.
Reuse the canonical run's SQL from `metric-describe` when the metric carries its own dimension column, so the chart draws the same rows the decomposition read.

## 1. The measure per day with its baseline

The 35-day series from the detection step, with the 28-day median you computed as a literal second column, so the chart draws the break and the baseline as two lines.

```json
{
  "chart_id": "series",
  "title": "Net revenue per day, 2026-10-20 to 2026-11-23",
  "caption": "The 28-day median is the flat line. The break is on 2026-11-21.",
  "query": {
    "kind": "DataVisualizationNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "SELECT toDate(created) AS day, sum(amount) / 100 AS net_revenue, 41200 AS median_28d FROM stripe_charges WHERE created >= '2026-10-20' AND created < '2026-11-24' GROUP BY day ORDER BY day LIMIT 40"
    },
    "display": "ActionsLineGraph",
    "chartSettings": {
      "xAxis": { "column": "day" },
      "yAxis": [{ "column": "net_revenue" }, { "column": "median_28d" }],
      "showLegend": true
    }
  }
}
```

## 2. The change by the driver dimension

The decomposition query for the dimension that explains the move, as a bar pair per segment: base window vs current window.
For a ratio, send the mix effect and the rate effect per segment instead, computed as two `sumIf` ratios in the SQL, so the chart shows which effect carries the move.

```json
{
  "chart_id": "driver",
  "title": "Net revenue by plan, same weekdays before vs 2026-11-21",
  "caption": "The Pro plan in the EU carries 80% of the drop; every other plan holds.",
  "query": {
    "kind": "DataVisualizationNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "SELECT plan AS segment, sumIf(amount, created >= '2026-10-24' AND created < '2026-11-21' AND toDayOfWeek(created) = 5) / 100 / 4 AS base, sumIf(amount, created >= '2026-11-21' AND created < '2026-11-22') / 100 AS current FROM stripe_charges WHERE created >= '2026-10-24' AND created < '2026-11-22' GROUP BY segment ORDER BY abs(current - base) DESC LIMIT 20"
    },
    "display": "ActionsBar",
    "chartSettings": {
      "xAxis": { "column": "segment" },
      "yAxis": [{ "column": "base" }, { "column": "current" }],
      "showLegend": true
    }
  }
}
```

## 3. The measure per day by the driver dimension

The series split by the driver dimension, limited to the top segments from chart 2 so the lines stay readable.
This is one more query (count it), bounded to the same 35 days.

```json
{
  "chart_id": "series-by-driver",
  "title": "Net revenue per day by plan, 2026-10-20 to 2026-11-23",
  "query": {
    "kind": "DataVisualizationNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "SELECT toDate(created) AS day, plan AS segment, sum(amount) / 100 AS net_revenue FROM stripe_charges WHERE created >= '2026-10-20' AND created < '2026-11-24' AND plan IN ('pro', 'team', 'free') GROUP BY day, segment ORDER BY day LIMIT 200"
    },
    "display": "ActionsLineGraph",
    "chartSettings": {
      "xAxis": { "column": "day" },
      "yAxis": [{ "column": "net_revenue" }],
      "seriesBreakdownColumn": "segment",
      "showLegend": true
    }
  }
}
```

## The notebook cells

The notebook carries the same three charts as `sql` cells, with the prose between them, so a human can rerun each query:

| Cell             | Shape                                                                                                                                                                                                                |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prose section    | `cell_type: "markdown"`, `markdown: "## What moved\n\n- ..."`                                                                                                                                                        |
| Each chart       | `cell_type: "sql"`, `code: "<the same pinned SQL>"`, `visualization: {"display": "ActionsLineGraph", "chartSettings": {"xAxis": {"column": "day"}, "yAxis": [{"column": "net_revenue"}, {"column": "median_28d"}]}}` |
| The driver table | `cell_type: "sql"` with the decomposition query and no `visualization`, so it renders as a table with segment, base, current, delta and share                                                                        |

Layout, top to bottom: the hook (one sentence with the measure, the size and the driver), chart 1, the baseline and method, chart 2, the driver table, chart 3, what you ruled out, and the next step for the reader.
Read `visualization_warnings` on each cell result and fix the axes before you link the notebook from the report.

## On an edit

Re-send all three under the same `chart_id` values with their windows moved to the new evidence date; a chart whose SQL differs from one you ran only in its date literals does not need a fresh run.
