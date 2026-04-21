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

Metric investigation is a multi-step orchestration. This skill provides the decision tree;
each metric type has its own playbook reference with specific tool calls and recipes.

## When to use

Use this skill when the user asks a "why did X change?" question about a metric.
Examples: "DAU dropped last Tuesday", "signup conversion fell 20% this week",
"week-1 retention for the March cohort is worse than February",
"returning users crashed after the release".

Do not load this skill for ordinary metric-reading questions ("what is DAU?", "show me retention").
Only use it when there is an observed change to explain.

## Step 1 — Classify the metric

Every query payload has a `kind` field (`TrendsQuery`, `FunnelsQuery`, `RetentionQuery`,
`StickinessQuery`, `LifecycleQuery`, `PathsQuery`). That `kind` is the classification —
it determines which playbook to run. Do not ask the user to classify when you can read it.

### Read the kind from what the user is looking at

Check these sources in order:

1. **A query you've already run for this metric in this conversation** — the payload you passed to
   `posthog:query-trends`, `posthog:query-funnel`, etc. has a `kind` field.
2. **A saved insight the user referenced** (URL, `short_id`, or "insight X") — call `posthog:insight-get`
   and read the returned insight's `query.kind` (the insight resource has a `query` JSON blob with a
   `kind` field). If you also need the insight's numbers to confirm the anomaly, call
   `posthog:insight-query` with the same identifier — `insight-get` returns only metadata.
3. **A query JSON the user pasted directly** — read `kind` from the payload.

Map `kind` to the playbook file:

| kind              | Playbook                                                      |
| ----------------- | ------------------------------------------------------------- |
| `TrendsQuery`     | [trend-playbook.md](./references/trend-playbook.md)           |
| `FunnelsQuery`    | [funnel-playbook.md](./references/funnel-playbook.md)         |
| `RetentionQuery`  | [retention-playbook.md](./references/retention-playbook.md)   |
| `StickinessQuery` | [stickiness-playbook.md](./references/stickiness-playbook.md) |
| `LifecycleQuery`  | [lifecycle-playbook.md](./references/lifecycle-playbook.md)   |

`PathsQuery` is rarely the "metric" in a changed-metric investigation — paths describes behavior
between events rather than a metric that moves. Treat the path's end event as the metric and use
the Trend playbook.

### If the user hasn't pointed at anything

If the user reports a metric change in free text without giving you an insight, dashboard, or query,
**ask before guessing**. The user saw the change somewhere — a saved insight, a dashboard tile, an
ad-hoc chart, a screenshot — and that source is the ground truth for the investigation.

Ask for the URL, `short_id`, or a description of where they're seeing the metric. Then use the
corresponding source above (most often `posthog:insight-get` on a saved insight) to read the
`kind` directly.

If the metric spans multiple kinds (e.g., "retention and stickiness both dropped"),
run the playbooks in sequence — do not try to fuse them.

## Step 2 — Common opening moves

Apply these regardless of metric kind, before entering the playbook.

### 2.1 Confirm the anomaly and pin the window

Run the primary tool for the metric's kind with the user's metric definition.
Confirm the change exists and identify its start date within a day or two.
Record: baseline value, current value, delta (absolute and %), start of the anomaly window.

### 2.2 Check whether the change is variance

If the query already covers enough history to see the normal range, read it from there.
Otherwise, widen to 3–4× the user's interval (e.g., 90 days for a 7-day drop) or add
`compareFilter: {"compare": true}` to show the prior period alongside.

Single-interval spikes or dips can be real (deploy, campaign, brief outage) — investigate them.
If the movement looks like normal variance, flag that in the findings but continue the
investigation when the user asked for one.

### 2.3 Check for known changes in the window

What deployed, flagged, or experimented near the start of the anomaly? Four sources, in order
of typical signal strength:

1. **Feature flags updated in the window.** `posthog:feature-flag-get-all`, then filter the
   returned list client-side by `updated_at` falling in or just before the anomaly window.
   A flag whose rollout changed right before the movement is a strong candidate — confirm by
   breaking the metric down on `$feature/<flag_key>` in the playbook.
2. **Experiments started or ended in the window.** `posthog:experiment-get-all`, then check
   `start_date` / `end_date`. An experiment launching shifts metrics through its variant
   rollout; one concluding (traffic snapping back to control) can cause an apparent drop.
3. **Annotations.** `posthog:annotations-list` — look for `date_marker` values in or just
   before the window. Annotations mark deploys, releases, campaigns, and incidents _when
   someone remembered to log them_; absence doesn't mean nothing shipped.
4. **Commits** (if you have access to the code repository that ships this metric). `git log`
   for the window is the source of truth for what actually deployed — higher-signal than
   annotations, but only available when the agent can reach the repo. Skip if unavailable.

Any aligning candidate is a hypothesis, not a conclusion — confirm in the metric-specific
playbook (typically via a breakdown on `$feature/<flag_key>`, `app_version`, or `utm_source`).

## Step 3 — Run the playbook

Open the playbook file matching the `kind` from Step 1 and execute its numbered steps.
Each playbook references [shared-patterns.md](./references/shared-patterns.md) for reusable
recipes (property discovery, breakdown dimensions and interpretation, interval zoom, actor
drilldown, session recordings, error cross-check, `execute-sql` escape hatch).

Carry the record from Step 2.1 (baseline, current, delta, window) and any candidates from
Step 2.3 (flags, experiments, annotations, commits) into the playbook so they're available
for confirmation.

## Step 4 — Cross-check

Before finalizing the findings, run one control query to rule out coincidence.

Pick a segment that the suspected cause should **not** have affected, and rerun the primary
query there. If the metric is stable in the control segment, the hypothesis is strong.
If the metric moved in the control segment too, the cause is broader than you thought —
expand the investigation.

## Step 5 — Write findings

Produce the output-format report below.

Offer to save key charts as insights via `posthog:insight-create` so the user can return to the
analysis. If a likely cause is identified and no annotation exists for it, offer to create one
via `posthog:annotation-create` with the identified date so future investigations find it.

See [common-causes.md](./references/common-causes.md) for the standard cause taxonomy.

## Output format

Structure the report as:

```markdown
# Investigation: <metric description>

**Anomaly**: <baseline> → <current> (<delta> <direction>) starting <date>

## Likely cause

<most-confident hypothesis, one sentence>

**Evidence**

- <query result 1 that supports the hypothesis>
- <query result 2 that supports the hypothesis>
- <annotation / flag / experiment / commit if applicable>

## Possible causes (ruled out or lower confidence)

- <hypothesis>: <why ruled out or why lower confidence>

## Affected segment

- <properties shared by affected users/events — country, plan, version, etc.>

## Data gaps

- <checks skipped and why>

## Suggested follow-ups

- <concrete next action — monitor metric X, check event Y, review deploy Z>
- <offer to save chart as insight / create annotation>
```

Include direct links where useful: `[Insight: name](/insights/short_id)`, `[Dashboard: name](/dashboard/id)`.

## Handling unavailable data

- **Missing breakdown dimension** — if a key property isn't set on events, call
  `posthog:properties-list` to confirm what is available and note the gap.
- **Tool call failure** — continue the investigation with the remaining tools and report
  which steps were skipped.
- **Variance / single-point anomalies** — covered in Step 2.2. If the change is within
  normal variance, flag it but continue when the user asked for an investigation.

## Reference files

- **Playbooks** (one per metric kind — open the one matching your classification):
  - [trend-playbook.md](./references/trend-playbook.md)
  - [funnel-playbook.md](./references/funnel-playbook.md)
  - [retention-playbook.md](./references/retention-playbook.md)
  - [stickiness-playbook.md](./references/stickiness-playbook.md)
  - [lifecycle-playbook.md](./references/lifecycle-playbook.md)
- [shared-patterns.md](./references/shared-patterns.md) — reusable recipes used across
  playbooks (property discovery, breakdown dimensions, interval zoom, actor drilldown,
  session recordings, error cross-check, `execute-sql` escape hatch).
- [common-causes.md](./references/common-causes.md) — taxonomy of likely causes with the
  confirming query for each.
