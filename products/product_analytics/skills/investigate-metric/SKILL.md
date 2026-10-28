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

The findings go in a walkthrough when the chart is a `TrendsQuery` over time (not a box plot, 2D heatmap or scatter plot) and `posthog:explain-chart` exists in this session.
It exists when `posthog:render-ui` lists `explain-chart` in its `tool_name`, or when `info explain-chart` works through `exec`.
Without `render-ui`, only some hosts draw the walkthrough from `exec`, so Step 5 checks that it appeared and falls back to the written report when it did not.
Otherwise the findings go in a written report.

When it is a walkthrough:

- Read the `explain-chart` schema now.
- Add "Show the walkthrough (Step 5)" as the last item of your plan or to-do list.
- Keep the `TrendsQuery` behind each finding, such as an event count with a breakdown or a property filter.
  The walkthrough draws a `TrendsQuery` as a chart beside the finding, and any other query only as a link.
  Use SQL for the findings that a `TrendsQuery` cannot express.

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

Use the format you chose in Step 1: the walkthrough when `explain-chart` exists and the chart is a `TrendsQuery` over time, and the written report otherwise.

### The walkthrough

It draws the chart with each moment highlighted and lets the user step through them.
Map the investigation onto it:

- **Anomaly** → one chapter per moment, with `start` and `end` copied exactly from the
  chart's `days`. The app works out each chapter's numbers from the chart, so leave them out
  of `summary`.
- **Likely cause** and **Confidence** → `cause`, `confidence` and `confidence_reason`.
- **Evidence** → `evidence`, each finding with the `query` that produced it, or a `url`
  for a commit or a deploy. Pass the `TrendsQuery` you ran where you have one: the
  walkthrough draws it as a chart, while any other query only becomes a link.
- A **headline** of one sentence with no numbers sums up the whole chart.
  Wrap each name behind a moment, such as the referrer of a spike or the country behind a rise, in `**double asterisks**` so the walkthrough highlights it.
  Do the same in each `cause`.

Call `posthog:explain-chart` first. It reports any chapter whose dates match no point on the
chart, so fix those dates and call it again.
When its response says the user already sees the result, the walkthrough is on screen, and you are done.
Otherwise call `posthog:render-ui` with `tool_name` `explain-chart` and the same input as `tool_input`.
When `render-ui` does not exist either, the user sees nothing, so write the written report instead.

Then reply in at most three short sentences: which chapter to look at first, one caveat
about the data if the walkthrough cannot show it, and one offer from below. The walkthrough
already holds the chart, the chapters, their causes and their evidence, so the reply has no
bullet points, no description of the chart and no list of the moments.

### The written report

Without the walkthrough, use the format below. Offer to save key charts via `posthog:insight-create`.
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
