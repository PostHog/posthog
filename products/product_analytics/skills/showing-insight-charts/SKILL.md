---
name: showing-insight-charts
description: >
  Draws PostHog insight or query results as a chart PNG on the local computer with
  @posthog/quill-charts, the chart library of the PostHog app, and shows the chart in the
  terminal or the system image viewer. Use when the user asks to see, show, plot, or chart
  PostHog data, or after a trends or funnel query when a chart helps the user. Makes no
  export, sends no request to PostHog, and needs no API key.
---

# Showing insight charts

You already have the data from the PostHog MCP. `scripts/render.mjs` draws it with `@posthog/quill-charts` in a headless browser and saves a PNG.
Then show the PNG to the user.

## Setup

Run this one time in this skill's `scripts/` directory. It installs the packages and builds `bundle.js`:

```bash
npm install
```

The script uses Google Chrome. If Chrome is not installed, also run `npx playwright install chromium` in the same directory.

## 1. Get the data

Use the PostHog MCP as usual, for example `query-trends`, `query-funnel`, or `insight-get`.
Use the numbers exactly as the query returns them. Do not fill gaps or round the values.

## 2. Draw the chart

Write a spec and run `scripts/render.mjs`:

```bash
node <skill-dir>/scripts/render.mjs /tmp/posthog-chart-<short-name>.png <<'SPEC'
{"title": "Daily active users", "subtitle": "Trends · Last 14 days", "kind": "line",
 "x": ["2026-09-27", "2026-09-28", "2026-09-29"],
 "series": [{"name": "Chrome", "values": [1801, 3709, 3635]}, {"name": "Safari", "values": [87, 535, 507]}]}
SPEC
```

- `kind`: `line` for a value over time. `bar` for categories, for example funnel steps or breakdown totals.
- `x`: for `line`, ISO dates or date-times from the query, for example `2026-09-27`. The chart formats them. For `bar`, the category names.
- `series`: one entry for each line or bar group. Use 10 series or fewer. Put the smallest ones together as `Other`. Use `null` for a missing value.
- `unit`: optional suffix for the y axis, for example `%` for conversion rates.
- `subtitle`: optional. Use the insight type and the date range.
- `timezone`: optional. The project timezone for `line` charts. The default is `UTC`.

The command prints the PNG path.

## 3. Show the chart

In Claude Code with the show-your-work plugin (Ghostty or kitty on macOS), call its `show_image` tool with:

- `path`: the PNG path
- `title`: the insight name, or a short description of the query
- `url`: the insight URL in PostHog, if the insight is saved. This adds an "Open page" button.

When you show a changed version of a chart that you showed before, set `previous` to the handle of the earlier result, so the user can compare the two versions.

If `show_image` is not available, open the PNG with `open` on macOS or `xdg-open` on Linux, and give the user the path.

## Rules

- Read the PNG yourself only when you must describe the chart. An image costs many tokens.
- The chart can show customer data. Keep the PNG in `/tmp`. Do not upload it or commit it.
