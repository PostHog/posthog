---
name: investigate-metric
description: >
  Diagnose why a product metric changed (dropped, spiked, or plateaued) by
  orchestrating breakdowns, actors, paths, lifecycle, retention, and annotations
  queries. Use when the user reports an anomaly, asks "why did X change?", or
  needs root-cause analysis for a trend, funnel, retention, stickiness, or
  lifecycle metric.
---

# Investigating a metric change

For "why did X change?" questions about a saved insight, dashboard tile, or pasted query.
Don't load this skill for plain "what is X?" questions — only when there's an observed
change to explain.

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
| `posthog:execute-sql`            | HogQL — when no typed tool fits                  |
| `posthog:read-data-schema`       | Discover events, properties, sample values       |
| `posthog:insight-get` / `-query` | Fetch a saved insight's metadata / data          |

Plus the standard PostHog tools the playbooks reference by name (`feature-flag-get-all`,
`experiment-get-all`, `annotations-list`, `error-tracking-issues-list`, `query-logs`,
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

## Step 2 — Common opening moves

### 2.1 Confirm the anomaly

Run the primary tool. Record baseline, current, delta (absolute and %), and the start
of the anomaly window.

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
- `posthog:experiment-get-all` → `start_date` / `end_date` near the start.
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

Use the format below. Offer to save key charts via `posthog:insight-create`. If a
cause is found and no annotation marks it, offer `posthog:annotation-create`. See
[common-causes.md](./references/common-causes.md) for the cause taxonomy.

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
