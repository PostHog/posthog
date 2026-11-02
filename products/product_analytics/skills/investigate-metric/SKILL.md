---
name: investigate-metric
description: >
  Diagnose why a product metric changed (dropped, spiked, or plateaued) by
  orchestrating breakdowns, actors, paths, lifecycle, retention, and annotations
  queries. Use when the user reports an anomaly, asks "why did X change?", asks
  to explain or walk them through a chart, or needs root-cause analysis for a
  trend, funnel, retention, stickiness, or lifecycle metric.
---

# Investigating a metric change

For "why did X change?" questions about a saved insight, dashboard tile, or pasted query,
and for "explain this chart" or "walk me through this" when the user names no change.
Don't load this skill for plain "what is X?" questions — only when there's a chart or an
observed change to explain.

## Tools

Targets PostHog MCP v2. Typed query tools accept the query body directly — pass
`kind`, `series`, `dateRange` as top-level fields, do not wrap in `InsightVizNode`.

| Tool                             | Purpose                                          |
| -------------------------------- | ------------------------------------------------ |
| `posthog:query-trends`           | Trends (count over time)                         |
| `posthog:query-funnel`           | Funnels (multi-step conversion)                  |
| `posthog:query-retention`        | Retention (cohort return rates)                  |
| `posthog:query-stickiness`       | Stickiness (active days per user)                |
| `posthog:query-lifecycle`        | Lifecycle (new/returning/resurrecting/dormant)   |
| `posthog:query-paths`            | Paths (navigation flow)                          |
| `posthog:query-trends-actors`    | Users behind a trend bucket (trends source only) |
| `posthog:execute-sql`            | Existing SQL insights and custom analysis        |
| `posthog:read-data-schema`       | Discover events, properties, sample values       |
| `posthog:insight-get` / `-query` | Fetch a saved insight's metadata / data          |
| `posthog:explain-chart`          | Walk the user through a trends chart (Step 5)    |

Plus the standard PostHog tools the playbooks reference by name (`feature-flag-get-all`,
`experiment-list`, `annotations-list`, `query-error-tracking-issues-list`, `query-logs`,
`query-session-recordings-list`, `cohorts-list/-create`, `annotation-create`,
`insight-create`).

## Helper scripts

- [`compare_to_prior_periods.py`](./scripts/compare_to_prior_periods.py) — auto-detects
  interval and compares recent values to the natural cycle (day-of-week, hour-of-week,
  or sequential). Use to resolve step 2.2 cheaply.
- [`breakdown_attribution.py`](./scripts/breakdown_attribution.py) — ranks breakdown
  segments by absolute delta and flags offsetting moves.

```bash
python3 scripts/compare_to_prior_periods.py < query_result.json
WINDOW=7 python3 scripts/breakdown_attribution.py < breakdown_result.json
```

## Step 1 — Classify the metric

Read `query.kind` from the source the user pointed at:

- Saved insight (URL, `short_id`): `posthog:insight-get` → `query.kind`. Use
  `posthog:insight-query` if you also need the numbers.
- A query you already ran or the user pasted: read `kind` directly.
- Nothing pointed at: ask for the URL or short_id. Don't guess.

| kind              | Playbook                                                      |
| ----------------- | ------------------------------------------------------------- |
| `TrendsQuery`     | [trend-playbook.md](./references/trend-playbook.md)           |
| `FunnelsQuery`    | [funnel-playbook.md](./references/funnel-playbook.md)         |
| `RetentionQuery`  | [retention-playbook.md](./references/retention-playbook.md)   |
| `StickinessQuery` | [stickiness-playbook.md](./references/stickiness-playbook.md) |
| `LifecycleQuery`  | [lifecycle-playbook.md](./references/lifecycle-playbook.md)   |
| `PathsQuery`      | [paths-playbook.md](./references/paths-playbook.md)           |
| `HogQLQuery`      | route by what the SQL aggregates (see below)                  |

If `kind === "TrendsQuery"` and `trendsFilter.display === "BoxPlot"`, use
[box-plot-playbook.md](./references/box-plot-playbook.md) — distribution metric, no
breakdowns.

For `HogQLQuery` insights, classify by the SQL's shape: count over time → trend
playbook, multi-step conversion → funnel playbook, cohort return → retention playbook.
Run the SQL through `posthog:execute-sql` to get the data, then follow the closest
playbook's steps. See **HogQL insights** in shared-patterns.md.

If the user's question spans multiple kinds, run the playbooks in sequence.

### Choose how you will show the findings

Decide this now, before the investigation, because it changes which queries you keep.

When the user gave you a saved insight or a query that is a `TrendsQuery` over time (not a box plot, 2D heatmap or scatter plot), the investigation ends with a chart explanation from `posthog:explain-chart`.
`posthog:explain-chart` exists only where chart explanations are enabled, so check for it now and read its schema.
Where PostHog tools run through `exec`, it is not in your own tool list: run `info explain-chart` before you decide it is missing.
When it does not exist, the findings go in a written report.
The chart explanation is the answer, in place of a notebook or a long reply. Write a notebook as well only when the user asks for one.
For anything else, such as a metric you queried on your own, the findings go in a written report.

When it is a chart explanation:

- Add "Show the chart explanation (Step 5)" as the last item of your plan or to-do list.
- Keep the query behind each finding. The chart explanation runs it again and draws the result beside the finding.
  Prefer an insight query, such as a `TrendsQuery` with a breakdown or a property filter, and use SQL only for what an insight query cannot express.

## Step 2 — Common opening moves

### 2.1 Confirm the anomaly

Run the primary tool. Record baseline, current, delta (absolute and %), and the start
of the anomaly window.

When the user asked you to explain a trends chart over time and named no change, find what
stands out first with [what-stands-out.md](./references/what-stands-out.md). Each moment it
finds becomes its own anomaly to run through the rest of the steps, most striking first.
For funnels, retention, paths and other kinds, use that kind's playbook to choose what to look into.

### 2.2 Variance check

Widen to 3–4× the user's interval (or use `compareFilter: {"compare": true}` on
TrendsQuery / StickinessQuery; for other kinds run two date ranges).
Pipe the widened result through
[`compare_to_prior_periods.py`](./scripts/compare_to_prior_periods.py) — it flags
seasonality, partial right-edge buckets, and real anomalies. If the movement is
normal variance, report that and stop.

### 2.3 Known changes in the window

In rough order of signal:

- `posthog:feature-flag-get-all` → flags with `updated_at` near the anomaly start.
- `posthog:experiment-list` → `start_date` / `end_date` near the start.
- `posthog:annotations-list` → `date_marker` near the start.
- `git log` for the window if the repo is reachable (highest signal when available).

Any match is a hypothesis to confirm in the playbook (usually via breakdown on
`$feature/<flag_key>`, `app_version`, or `utm_source`).

## Step 3 — Run the playbook

Open the playbook for the kind from Step 1 and follow its numbered steps. Carry the
record from 2.1 and any candidates from 2.3 into it.

## Step 4 — Cross-check

Pick a segment the suspected cause should **not** have affected and rerun there. Stable
in the control = strong hypothesis; moved too = expand the investigation. Skip when
2.2 already explained the movement.

## Step 5 — Write findings

**Before you write your answer, call `posthog:explain-chart` when the user gave you a trends insight over time.**
Do this after a long investigation too, and when most of your evidence is SQL.
For anything else, use the written report.

### The chart explanation

It draws the chart with each moment highlighted and lets the user step through them.
Map the investigation onto it:

- **Anomaly** → one chapter per moment, with `start` and `end` copied exactly from the
  chart's `days`. The app works out each chapter's numbers from the chart, so leave them out
  of `summary`.
- **Likely cause** and **Confidence** → `cause`, `confidence` and `confidence_reason`.
- **Evidence** → `evidence`, each finding with the `query` that produced it, or a `url`
  for a commit or a deploy. The chart explanation runs each query and draws it: an insight
  query with its insight chart, and a `HogQLQuery` from its rows. Shape the SQL for the chart,
  with the x-axis column first, then optionally one text column to break down by, then the numbers.
  Prefer a series over time to a before-and-after comparison, so the user sees when the change happened.
- **Zoomed-in evidence** → when the metric moved suddenly, add one finding that zooms in on the change.
  Use the insight's own query with a `dateRange` around the change, at the interval that shows it best, from `minute` to `day`.
  Filter it to the segment the cause points at, such as the affected browser or region.
- A **headline** of one sentence with no numbers sums up the whole chart.
  Wrap each name behind a moment, such as the referrer of a spike or the country behind a rise, in `**double asterisks**` so the chart explanation highlights it.
  Do the same in each `cause`.

Call `posthog:explain-chart` first. It reports any chapter whose dates match no point on the
chart, so fix those dates and call it again.
When its response says the user already sees the result, the chart explanation is on screen, and you are done.
Otherwise call `posthog:render-ui` with `tool_name` `explain-chart` and the same input as `tool_input`.
When the call fails because the tool does not exist, or `render-ui` does not exist either, the user sees nothing, so write the written report instead.

Then reply briefly.
Say which chapter to look at first, then add only what the chart explanation cannot hold, such as a caveat about the data, a linked fix or a decision that is still open.
End with one offer from below.
The chart explanation already holds the chart, the chapters, their causes and their evidence, so do not describe the chart or list the moments again.

### The written report

Without the chart explanation, use the format below. Offer to save key charts via `posthog:insight-create`.
If a cause is found and no annotation marks it, offer `posthog:annotation-create`.
See [common-causes.md](./references/common-causes.md) for the cause taxonomy.

```markdown
# Investigation: <metric>

**Anomaly**: <baseline> → <current> (<delta>) starting <date>

## Likely cause

<one sentence>

**Confidence**: low | medium | high — <one-line reason>

**Evidence**

- <query result>
- <flag / experiment / annotation / commit if applicable>

## Possible causes (ruled out)

- <hypothesis>: <why>

## Affected segment

- <shared properties of affected users/events>

## Data gaps

- <checks skipped and why>

## Suggested follow-ups

- <concrete next action>
- <offer to save chart / create annotation>
```

**Confidence** rule of thumb:

- **high** — multiple independent signals corroborate (e.g. a segment isolates the
  delta _and_ a flag/version aligns _and_ an error or annotation matches).
- **medium** — one corroborating signal, or strong pattern-match without a
  cross-check.
- **low** — pattern matches a known cause but no corroboration, or the data only
  rules things _out_.

Link insights and dashboards inline: `[Name](/insights/short_id)`.

## Reference files

- Playbooks: [trend](./references/trend-playbook.md),
  [box-plot](./references/box-plot-playbook.md),
  [funnel](./references/funnel-playbook.md),
  [retention](./references/retention-playbook.md),
  [stickiness](./references/stickiness-playbook.md),
  [lifecycle](./references/lifecycle-playbook.md),
  [paths](./references/paths-playbook.md)
- [shared-patterns.md](./references/shared-patterns.md) — recipes used across playbooks
- [common-causes.md](./references/common-causes.md) — cause taxonomy with confirming queries
