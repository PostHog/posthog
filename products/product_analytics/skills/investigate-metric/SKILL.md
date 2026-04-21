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

Metric investigation is a multi-step orchestration across several structured query tools.
Each metric type (trend, funnel, retention, stickiness, lifecycle) has a different investigation shape,
and the first decision you make — **what kind of metric is this?** — determines which tools to reach for.

See [query patterns](./references/query-patterns.md) for copy-pasteable tool call payloads and a
note on when to use `posthog:execute-sql` vs. the structured query tools.

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

Map `kind` → playbook: `TrendsQuery` → Trend, `FunnelsQuery` → Funnel, `RetentionQuery` → Retention,
`StickinessQuery` → Stickiness, `LifecycleQuery` → Lifecycle.

`PathsQuery` is rarely the "metric" in a changed-metric investigation — paths describes behavior
between events rather than a metric that moves. Treat the path's end event as the metric and run
the Trend playbook on it.

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

Apply these regardless of metric kind.

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

What deployed, flagged, or experimented near the start of the anomaly? Three sources, in order
of typical signal strength:

1. **Feature flags updated in the window.** `posthog:feature-flag-get-all`, then filter the
   returned list client-side by `updated_at` falling in or just before the anomaly window.
   A flag whose rollout changed right before the movement is a strong candidate — confirm by
   breaking the metric down on `$feature/<flag_key>` in the Trend playbook.
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

## Step 3 — Metric-type-specific investigation

Execute only the playbook for the metric kind you classified in Step 1.

### Trend metrics

1. **Zoom in on the anomaly window.** Rerun `posthog:query-trends` with a finer `interval`
   (typically `"hour"`, or `"minute"` for short windows) scoped tightly to the suspicious day(s).
   Hourly resolution reveals the _shape_ of the anomaly: a narrow spike or cliff points to a
   specific incident / deploy / cron job; a sustained shift points to broader causes (campaign,
   cohort change, tracking regression).
2. **Break down the trend.** Run several breakdowns to see if one segment is driving the
   change. Rerun `posthog:query-trends` with different `breakdownFilter.breakdowns` values.

   Property discovery for dimensions you don't know about up front:
   - `posthog:properties-list` with `type: "event"` and `eventName: "<your event>"` — custom
     properties the app sets on this specific event (e.g. `plan`, `tier`, `feature_area`,
     `channel`). Often the most diagnostic dimension for product-specific metrics.
   - `posthog:properties-list` with `type: "person"` — person-level properties.

   Dimensions to try:
   - **Standard event context** — `$browser`, `$browser_version`, `$os`, `$device_type`,
     `$screen_width`, `$geoip_country_code`. Always available; a drop concentrated in one
     platform is often a tracking or rendering bug.
   - **Feature-flag exposure** — `$feature/<flag_key>` separates exposed vs. control users.
     Highest-signal for post-release investigations.
   - **User state** — authenticated vs anonymous (`is_identified` on the person), new vs
     returning (`$is_first_session` on the event), plan / tier on the person.
   - **Custom event properties** you discovered above — project-specific, often diagnostic.
   - **Technical / version** — `app_version`, `$lib_version` for SDK regressions.

   If one breakdown value absorbs most of the delta, that's the affected segment — but measure
   this in **absolute** terms, not percentages. A 50% swing on a series that's 1% of volume
   explains only 0.5% of the aggregate delta. Check each series' volume and its absolute
   contribution to the total change before concluding it's the driver — a visually dramatic
   movement on a small series is usually noise.

   If no breakdown value isolates the delta, the cause is likely system-wide (bad deploy,
   tracking regression, infra issue) rather than segment-specific — note the negative result
   and move on to the next steps. Breakdowns find segment-shaped causes; they're silent on
   system-wide ones.

   If you suspect an interaction between two dimensions (e.g., a browser bug that only
   affects one country), try a compound breakdown with up to three properties in `breakdowns`.
   If the event fires fewer than ~100 times per interval, percentage changes are unreliable —
   report absolute numbers alongside percentages.

3. **Identify the affected users.** `posthog:query-trends-actors` on the anomalous bucket
   (specific day/hour or specific breakdown value). Inspect returned persons' properties for
   common threads. For a UI/UX-driven drop, also call `posthog:query-session-recordings-list`
   filtered to the same window and segment — watching a few recordings is often the fastest
   way to confirm what users are actually doing.
4. **Cross-check against errors / logs.** Call `posthog:error-tracking-issues-list` and
   `posthog:query-logs` filtered to the anomaly window. A correlated error is a candidate,
   not a conclusion — to confirm, check that the error timing aligns with the drop, that
   the error actually affects the metric's surface (a 500 on a submit endpoint can plausibly
   cause failures; a console warning elsewhere usually can't), and that the users hitting
   the error overlap with the affected segment.
5. **Check if it's a cohort-composition change.** `posthog:query-lifecycle` on the same metric.
   A drop concentrated in one lifecycle status (new didn't arrive, dormant didn't resurrect)
   reframes the investigation.

### Funnel metrics

1. **Confirm which step regressed.** `posthog:query-funnel` with the user's steps. Identify the
   step where conversion dropped.
2. **Is it entries or completions?** `posthog:query-trends` on the count of the failing step
   alone, compared to the count of the step before. If entries are steady but completions fell,
   the problem is at that step. If entries also fell, the problem is upstream. Consider zooming
   `interval` to `"hour"` if a specific day looks anomalous.
3. **Who is dropping off?** `posthog:query-trends-actors` only accepts a trends source today
   (no direct funnel-actors mode). Work around it by running a `posthog:query-trends` on the
   last completed step filtered to users who did _not_ perform the failing step within the
   funnel window, then pass that trend to `posthog:query-trends-actors`. For UI/UX drop-offs,
   also pull session recordings via `posthog:query-session-recordings-list` filtered to the
   window and the relevant events — watching a few is often faster than more queries. See
   [query patterns](./references/query-patterns.md) for the exact shape.
4. **Cross-check against errors.** `posthog:error-tracking-issues-list` filtered to the surface
   where step N lives. An error is a candidate, not a confirmation — to tie it to the funnel
   drop, verify that the error's volume timing aligns with the drop in completions, that it
   actually blocks the step (a 500 at submit explains failures; a console warning probably
   doesn't), and that the users hitting it overlap with those who dropped out at step N.
5. **What are they doing instead?** `posthog:query-paths` with `endPoint` set to the failing
   step. The paths that do not reach the end point show what users do when they bail.

### Retention metrics

For "week-N retention regressed", "March cohort isn't coming back".

1. **Isolate the affected cohort.** `posthog:query-retention` broken out by start cohort.
   Compare affected cohorts to baseline cohorts side-by-side.
2. **Scope to the retained-activity event.** `posthog:query-trends` on the event that defines
   "retained" in the user's retention metric, filtered to users in the affected cohort (create
   or reuse a cohort via `posthog:cohorts-create` / `posthog:cohorts-list`). Is the drop in the
   event itself, or in the users doing the event?
3. **Split the dropout.** `posthog:query-lifecycle` on the affected cohort — distinguish new
   users who never returned after week 0 from returning users who churned later.

### Stickiness metrics

For "DAU/MAU dropped", "sessions per week fell", "engagement decayed".

1. **Who got less sticky?** `AssistantStickinessQuery` does not support `breakdownFilter`.
   To compare segments, run `posthog:query-stickiness` once per segment with different property
   filters on the series (e.g., one call with `properties: [{key: "plan", value: "pro", ...}]`,
   another with `{value: "free"}`). Identify the segment whose stickiness fell.
2. **Identify the affected users.** Run `posthog:query-trends` on a key engagement event filtered
   to the low-stickiness segment, then `posthog:query-trends-actors` on that trend to get the
   affected users. Pull a handful of session recordings via `posthog:query-session-recordings-list`
   to see how they're actually using the product.
3. **Compare engagement events between sticky and non-sticky segments.** Create cohorts (or
   filters) for high-stickiness and low-stickiness users, then run `posthog:query-trends` on
   candidate core events scoped to each cohort. The events that differ sharply between the two
   cohorts are the ones that drive stickiness.

### Lifecycle metrics

For "new user acquisition fell", "returning users crashed", "resurrecting users stopped coming back".

1. **`posthog:query-lifecycle` is already the primary tool.** Start with the user's metric and
   identify which lifecycle status (new, returning, resurrecting, dormant) moved.
2. **Segment the moved status.** `AssistantLifecycleQuery` does not support `breakdownFilter`.
   To isolate a slice, rerun `posthog:query-lifecycle` with property filters on the series
   (e.g., one call filtered to `plan = "pro"`, another to `plan = "free"`). Alternatively, use
   `lifecycleFilter.toggledLifecycles` to focus on a specific status.
3. **Diagnose based on status:**
   - _New-user drop_ — identify the canonical first-session event in the project via
     `posthog:event-definitions-list` (commonly `$session_start`, `$pageview`, or a product-specific
     signup event). Then `posthog:query-paths` from that event to see where new users fall off
     in onboarding.
   - _Returning-user drop_ — `posthog:query-trends` on the affected cohort's key engagement events.
     Zoom `interval` to `"hour"` if a specific day stands out.
   - _Resurrecting drop_ — compare marketing/re-engagement campaign annotations in the window.

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

See [common causes](./references/common-causes.md) for the standard cause taxonomy.

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
- <annotation or external signal if applicable>

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

- **Missing breakdown dimension** — if a key property (e.g., `app_version`) isn't set on events,
  call `posthog:properties-list` to confirm what is available and note the gap.
- **Tool call failure** — continue the investigation with the remaining tools and report which
  steps were skipped.
- **Variance / single-point anomalies** — covered in Step 2.2. If the change is within normal
  variance, stop there.

## Reference files

- [Query patterns](./references/query-patterns.md) — copy-pasteable MCP tool call payloads,
  organized by metric type, plus the `execute-sql` escape hatch.
- [Common causes](./references/common-causes.md) — taxonomy of likely causes with the
  confirming query for each.
