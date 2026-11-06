---
name: formatting-insight-axes
description: >
  Pick the right y-axis unit when creating or updating an insight via
  `posthog:insight-create` or `posthog:insight-update` — both TrendsQuery
  (`trendsFilter.aggregationAxisFormat`) and SQL insights
  (`DataVisualizationNode`, `chartSettings.yAxis[].settings.formatting`).
  Use when the agent is about to add a `formula` purely to convert units
  (e.g. dividing seconds by 60 to display minutes), when a `math_property`
  or SQL column is a duration, currency, ratio, or large count, or whenever
  the user mentions "format the y-axis", "duration", "seconds", "minutes",
  "hours", "milliseconds", "ms", "percentage", "%%", "currency", "decimals",
  "axis label", or "axis unit" in the context of a graph insight.
---

# Formatting insight axes

PostHog renders insights with a built-in axis formatter. Use it instead of
contorting the query or a literal prefix/postfix to fake units.

The two insight kinds configure it in different places:

- **TrendsQuery** — `trendsFilter.aggregationAxisFormat` (this page, below)
- **SQL insights** (`DataVisualizationNode`) — per-column
  `settings.formatting` (see [SQL insights](#sql-insights-datavisualizationnode))

## The anti-pattern

If you are reaching for any of these, stop and pick a format below first:

- `formula: "A / 60"` with `aggregationAxisPostfix: " mins"` — manual seconds -> minutes
- `formula: "A / 1000"` with `aggregationAxisPostfix: " s"` — manual ms -> seconds
- `formula: "A * 100"` with `aggregationAxisPostfix: "%"` — manual ratio -> percent
- `aggregationAxisPostfix: "ms"` / `"s"` / `"min"` / `"hr"` on raw values

These freeze the unit at one scale. The built-in formatter picks a friendly
unit per value (1.5s, 2m 12s, 1h 4m) and keeps the underlying series numerically
correct for further math, breakdowns, and alerts.

## Available formats

Set `trendsFilter.aggregationAxisFormat` on the TrendsQuery:

| Value               | Use when the series is...                | Renders as                  |
| ------------------- | ---------------------------------------- | --------------------------- |
| `numeric` (default) | a plain count                            | `1,234`                     |
| `duration`          | **seconds** (any scale)                  | `45s`, `2m 12s`, `1h 4m`    |
| `duration_ms`       | **milliseconds**                         | `850ms`, `1.5s`, `1m 4s`    |
| `percentage`        | already 0-100                            | `47.3%`                     |
| `percentage_scaled` | a ratio 0-1                              | `47.3%`                     |
| `currency`          | money in the **project's base currency** | `$1,234.56` (or local code) |
| `short`             | large counts you want compacted          | `1.2K`, `3.4M`              |

Companion fields on `trendsFilter`:

- `aggregationAxisPrefix` — literal prefix (e.g. `"$"`) when you need a symbol
  pinned to a specific currency or unit, regardless of project settings
- `aggregationAxisPostfix` — literal suffix; reserve for genuine units the
  format can't express (e.g. `" req"`, `" events"`), never for `"mins"` /
  `"s"` / `"%"` — the percentage formats already append the `%` sign, so a
  `"%"` postfix renders `50%%`
- `decimalPlaces` — cap decimals (1 or 2 is usually right for currency / ratios)

### Currency — pick `format` or `prefix` carefully

`aggregationAxisFormat: "currency"` renders with the **project's base currency**
(set in project settings, defaults to USD). Use it when the underlying values
are in that same currency — e.g. revenue events that PostHog auto-converts to
the project's base currency.

If the values are pinned to a specific currency regardless of project (e.g.
`$ai_total_cost_usd` is always USD, even on a EUR-base project), use
`aggregationAxisPrefix: "$"` + `decimalPlaces: 2` so the symbol matches the
data. Using `format: "currency"` here would render USD values with `€` on a
EUR project.

## When the series is in seconds

If the series is in seconds (latency, session length, time-to-first-event,
processing time, page load, etc.), silently default to
`aggregationAxisFormat: "duration"`. Do not stop to ask — the formatter is
non-destructive (the underlying values stay in seconds either way, only the
labels change), so picking it is always at least as good as raw seconds.

Only confirm with the user when they have **explicitly** named a fixed unit
they want pinned ("show this in minutes", "graph the average in hours"):

> "I can pin the y-axis to minutes by dividing the series by 60, or use
> PostHog's `duration` formatter which auto-picks seconds / minutes / hours
> per value — `90s` renders as `1m 30s` and `5400s` as `1h 30m`. Which would
> you prefer?"

In one-shot MCP contexts where no user is in the loop, just pick `duration`
and move on.

## Examples

### Latency — duration in milliseconds

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "math": "p95",
      "math_property": "$performance_page_loaded"
    }
  ],
  "trendsFilter": {
    "aggregationAxisFormat": "duration_ms"
  }
}
```

### Average session length — duration in seconds

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageleave",
      "math": "avg",
      "math_property": "$session_duration"
    }
  ],
  "trendsFilter": {
    "aggregationAxisFormat": "duration"
  }
}
```

### Revenue — currency in the project's base currency

```json
{
  "trendsFilter": {
    "aggregationAxisFormat": "currency",
    "decimalPlaces": 2
  }
}
```

### Fixed-currency value (e.g. LLM cost in USD) — pin the symbol

```json
{
  "trendsFilter": {
    "aggregationAxisPrefix": "$",
    "decimalPlaces": 2
  }
}
```

### Conversion rate — percentage from a 0-1 formula

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "checkout_completed",
      "math": "dau"
    },
    {
      "kind": "EventsNode",
      "event": "checkout_started",
      "math": "dau"
    }
  ],
  "trendsFilter": {
    "formula": "A / B",
    "aggregationAxisFormat": "percentage_scaled",
    "decimalPlaces": 1
  }
}
```

## SQL insights (DataVisualizationNode)

SQL insights have no `trendsFilter`.
Formatting is per column, on `chartSettings.yAxis[].settings.formatting` for a chart and top-level `tableSettings.columns[].settings.formatting` for a table.

```json
{
  "kind": "DataVisualizationNode",
  "source": { "kind": "HogQLQuery", "query": "SELECT week, conversion_rate FROM ..." },
  "display": "ActionsLineGraph",
  "chartSettings": {
    "xAxis": { "column": "week" },
    "yAxis": [
      {
        "column": "conversion_rate",
        "settings": { "formatting": { "style": "percent", "decimalPlaces": 1 } }
      }
    ]
  }
}
```

`style` is `none`, `number`, `short`, or `percent` — no `duration` or `currency`.
Express those with `prefix` / `suffix`, or in the SQL itself.

`percent` both appends the `%` sign and multiplies the value by 100 (like the trends `percentage_scaled` format; there is no unscaled variant).
So feed it a 0-1 ratio and leave `suffix` unset — pick one shape, never a mix:

| SQL returns                       | `formatting`                                             | Renders |
| --------------------------------- | -------------------------------------------------------- | ------- |
| a 0-1 ratio (`a / b`)             | `{"style": "percent", "decimalPlaces": 1}`               | `47.3%` |
| 0-100 (`round(100.0 * a / b, 1)`) | `{"style": "number", "suffix": "%", "decimalPlaces": 1}` | `47.3%` |

A mix renders broken: `style: "percent"` plus a `"%"` suffix gives `47.3%%`, and `percent` on an already-scaled 0-100 column gives `4730%`.
Prefer the ratio form — it keeps the `100.0 *` out of the query, so the stored column stays a plain ratio for anything else that reads it.

## Updating an existing insight

If an insight you are already editing uses one of these anti-patterns — a
trends `formula`/`postfix` pair, or a SQL column with both `style: "percent"`
and a `"%"` suffix — fix it in the same `posthog:insight-update` call: drop the
divide-by-N or `100.0 *` and the literal `%`, and let the format own the unit.
Values stay the same, only labels change. Do not scan unrelated insights — fix
only the ones you are already touching.
