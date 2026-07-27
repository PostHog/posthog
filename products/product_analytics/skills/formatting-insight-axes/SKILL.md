---
name: formatting-insight-axes
description: >
  Pick the right y-axis unit when creating or updating a TrendsQuery insight
  via `posthog:insight-create` or `posthog:insight-update`. Use when the agent
  is about to add a `formula` purely to convert units (e.g. dividing seconds
  by 60 to display minutes), when a `math_property` is a duration, currency,
  ratio, or large count, or whenever the user mentions "format the y-axis",
  "duration", "seconds", "minutes", "hours", "milliseconds", "ms",
  "percentage", "currency", "decimals", "axis label", or "axis unit" in the
  context of a graph insight.
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

## Updating an existing insight

If you are updating an insight and notice it already uses the
`formula`/`postfix` anti-pattern, fix it in the same `posthog:insight-update`
call — drop the divide-by-N, drop the `aggregationAxisPostfix`, and set the
matching `aggregationAxisFormat`. The series values stay the same, only the
labels change. Do not go scanning unrelated insights for this pattern —
fix only the ones you are already touching.
