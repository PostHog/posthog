---
name: formatting-insight-axes
description: >
  Pick the right y-axis unit when creating or updating a TrendsQuery insight
  via `posthog:insight-create` or `posthog:insight-update`. Use when the agent
  is about to add a `formula` purely to convert units (e.g. dividing seconds
  by 60 to display minutes), when a `math_property` is a duration, currency,
  ratio, or large count, or whenever the user mentions "format the y-axis",
  "duration", "seconds", "minutes", "hours", "percentage", "currency",
  "decimals", "axis label", or "axis unit" in the context of a graph insight.
---

# Formatting insight axes

PostHog renders TrendsQuery insights with a built-in axis formatter. Use it
instead of contorting `formula` or `aggregationAxisPostfix` to fake units.

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

| Value               | Use when the series is...                | Renders as                   |
| ------------------- | ---------------------------------------- | ---------------------------- |
| `numeric` (default) | a plain count                            | `1,234`                      |
| `duration`          | **seconds** (any scale)                  | `1.5s`, `2m 12s`, `1h 4m`    |
| `duration_ms`       | **milliseconds**                         | `850ms`, `2.0s`, `1m 4.0s`   |
| `percentage`        | already 0-100                            | `47.3%`                      |
| `percentage_scaled` | a ratio 0-1                              | `47.3%`                      |
| `currency`          | money in the **project's base currency** | rendered with project symbol |
| `short`             | large counts you want compacted          | `1.2K`, `3.4M`               |

Companion fields on `trendsFilter`:

- `aggregationAxisPrefix` — literal prefix (e.g. `"$"`) when you need a symbol
  pinned to a specific currency or unit, regardless of project settings
- `aggregationAxisPostfix` — literal suffix; reserve for genuine units the
  format can't express (e.g. `" req"`, `" events"`), never for `"mins"` / `"s"`
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

## When seconds appear, offer the choice

If the series is in seconds (latency, session length, time-to-first-event,
processing time, page load, etc.) and the user has not already specified a
unit, default to `aggregationAxisFormat: "duration"`. If the user explicitly
asked for "minutes" or "hours" as a fixed unit:

> "I can show this with PostHog's `duration` formatter, which auto-picks
> seconds / minutes / hours per value — values like `90s` render as `1m 30s`
> and `5400s` render as `1h 30m`. Or I can fix the y-axis to minutes by
> dividing by 60. Which do you prefer?"

Default to `duration` unless the user wants the fixed unit. The series stays
in seconds either way — only the display changes.

## Examples

### Latency — duration over time

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
  "trendsFilter": {
    "formula": "A / B",
    "aggregationAxisFormat": "percentage_scaled",
    "decimalPlaces": 1
  }
}
```

## Updating an existing insight

If you find a saved insight that already uses the `formula`/`postfix`
anti-pattern, offer to fix it with `posthog:insight-update` — drop the
divide-by-N, drop the `aggregationAxisPostfix`, and set the matching
`aggregationAxisFormat`. The series values stay the same, only the labels
change.
