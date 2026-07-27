# PostHog numbers don't match the user's SQL / raw count

The experiment page applies a specific scope that ad-hoc SQL almost never replicates.
A common pattern: SQL is written "to verify" experiment numbers and the results don't match — most of
the time, the experiment numbers are correct and the SQL is missing one or more scope filters.

## Before walking this file

If the gap between **exposures and downstream metric counts** is very large (the metric is one or
two orders of magnitude smaller than exposures), don't anchor on SQL reconciliation. That shape of
divergence is most often a bucketing or identity-resolution problem, not a query-scope problem —
walk `bias-and-skew.md` first (especially A3 / A4) and only come back here once identity is ruled
out. The symptom often surfaces as "the numbers don't match", but the agent should route it to A
before D.

## Contents

- D1 — Scope mismatch checklist (the eight sources)
- D2 — Funnel: only first→last step counts for stats
- D3 — Breakdowns read from the _exposure_ event, not the metric event
- D4 — "Sum of revenue" = mean of per-user totals (not raw total)
- D5 — Property breakdowns silently return "none" for missing properties
- D6 — Recordings panel ≠ statistical calculation
- D7 — Conversion-window anchoring (differs by metric type)
- D8 — Cached results can lag behind ingestion
- D9 — Applying a filter doesn't change the user count
- D10 — No "current person properties" toggle on experiment metrics
- D11 — Metric definition traps (empty event filter, HogQL count(boolean))

## D1 — Scope mismatch checklist (the eight sources) [HIGH]

When the user reports "PostHog says X, my SQL says Y", walk this checklist:

1. **Exposure scope.** The experiment counts only events that occur after the user's first exposure.
   Raw counts don't filter this way.
2. **`$multiple` exclusion.** With default handling (`exclude`), multi-variant users are dropped from
   metrics. Raw counts include them.
3. **Test-account filter.** Defaults to `true` — internal/test users excluded. Raw counts don't
   typically apply it.
4. **Date range.** The experiment is bounded by `start_date` / `end_date`; raw counts often span more.
5. **Variant attribution.** The experiment uses the _exposure event's_ variant property; raw counts may
   pull variant from a different event.
6. **Conversion window** (funnel metrics only). Events outside the per-user conversion window are not
   counted. See D7.
7. **Per-user aggregation.** Mean / ratio metrics aggregate per-user before averaging, so the result is
   not a raw event-level total. See D4.
8. **Winsorization (outlier clamping) on mean metrics.** Mean metrics support a percentile-clamp
   configuration that replaces values below the lower percentile and above the upper percentile with
   the percentile values themselves before averaging. When enabled, no raw SQL `AVG`/`SUM` over the
   underlying events will reconcile — values are post-clamp.

   <!-- Source for maintainers: _build_mean_query_with_winsorization in
   posthog/hogql_queries/experiments/experiment_query_builder.py -->

**Recommend:** reproduce the experiment's scope in SQL exactly (start with `experiment-get`'s
`exposure_criteria`, `parameters`, and `stats_config`), or accept that ad-hoc SQL will not match by
design.

### Canonical scope-reproducing HogQL skeleton

Use this as the starting point when the user wants to reconcile. Fill the placeholders from
`experiment-get`. This reproduces sources 1, 2, 4, and 5 from the checklist directly; sources 3, 6,
and 7 are noted inline. Source 8 (winsorization) is not reproducible in a one-shot skeleton — if a
mean metric uses the percentile-clamp config, no raw `AVG`/`SUM` reconciles by design.

```sql
WITH exposures AS (
  SELECT
    person_id,
    argMin(properties.$feature_flag_response, timestamp) AS variant,
    min(timestamp) AS first_exposure
  FROM events
  WHERE event = '$feature_flag_called'  -- or exposure_criteria.exposure_event when set
    AND properties.$feature_flag = '<flag-key>'
    AND properties.$feature_flag_response != '$multiple'  -- source 2 (drop if multiple_variant_handling='first_seen')
    AND timestamp >= '<start_date>'                       -- source 4
    AND timestamp <= coalesce('<end_date>', now())        -- source 4
  -- source 3: append the project's test-account filter here when filterTestAccounts=true
  GROUP BY person_id
  HAVING variant != ''
)
SELECT
  u.variant,
  count(DISTINCT u.person_id) AS exposed_users,
  count(e.uuid) AS metric_events,
  -- For "mean of per-user totals" (D4), wrap a per-user sum first then average:
  -- avg(per_user_total) FROM (SELECT person_id, sum(toFloat(properties.<value-prop>)) AS per_user_total ...)
  count(e.uuid) / nullIf(count(DISTINCT u.person_id), 0) AS events_per_user
FROM exposures u
LEFT JOIN events e
  ON e.person_id = u.person_id
  AND e.event = '<metric-event>'                          -- keep this in the JOIN, not WHERE,
                                                          -- so users with 0 metric events still count
  AND e.timestamp >= u.first_exposure                     -- source 1
  AND e.timestamp <= coalesce('<end_date>', now())        -- source 4
  -- source 6: for funnel metrics, also gate e.timestamp <= u.first_exposure + INTERVAL '<conversion_window>'
GROUP BY u.variant
ORDER BY u.variant
```

Note: keep the metric-event filter in the JOIN's `ON` clause, not in a top-level `WHERE` — moving
it to `WHERE` would silently drop exposed users who never produced the metric event (`e.event` is
`NULL` for them), breaking the denominator.

Notes:

- **`multiple_variant_handling = 'first_seen'`**: drop the `!= '$multiple'` filter and keep
  `argMin(...)` — it already picks the first variant the user saw.
- **Funnel metrics** (D2): only the first-step → last-step conversion counts for stats. Intermediate
  steps are visualization-only. Reproduce by gating `e.event` on the _last_ step and joining the
  exposure as `step_0` implicitly.
- **"Sum of revenue"** (D4): wrap a per-user `sum(...)` subquery, then `avg(...)` across users in the
  variant — not `sum(...)` event-level.
- **Breakdowns** (D3): read the breakdown property from the exposure row in `exposures`, not from `e`.
- **Test-account filter** (source 3): the agent can either pull project settings and inline the
  filter, or recommend the user temporarily toggle `filterTestAccounts=false` and re-read the
  experiment to confirm that's the gap.

## D2 — Funnel: only first→last step counts for stats [HIGH]

For multi-step funnel metrics, **statistical significance is always calculated between the first
step (exposure) and the final step**. Intermediate steps are shown for analysis and visualization
but **do not affect the significance calculation nor win probability** — a user can read a significant intermediate
step and incorrectly conclude the whole funnel is significant.

**Implication:** comparing PostHog's funnel conversion rate to a SQL query that counts intermediate
conversions will not match — and that's expected.

The exposure event is automatically prepended as `step_0` for funnel metrics, so a 1-step funnel is
really a 2-step funnel: **exposure → action**. Conversion = % of exposed users who reached the action.

## D3 — Breakdowns read from the exposure event, not the metric event [HIGH]

When a user adds a breakdown (e.g. "by country" or "by device type") to an experiment metric, the
property is read from the **exposure event**, not the metric event. This is for statistical reasons —
the metric event happens after exposure, but the breakdown needs to partition users at the time of
exposure.

**Implication:** if the property only exists on the metric/conversion event (e.g. a checkout event with
`payment_method`), breaking down the experiment by it won't work — every user will appear under "none"
because the property isn't on the exposure event.

**Recommend:** if the user needs to break down by a property only set at conversion, they need to
either:

- Set the property earlier so it's present on the exposure event (preferred)
- Use the breakdown in product analytics instead, with the appropriate filter for variant

## D4 — "Sum of revenue" = mean of per-user totals (not raw total) [HIGH]

Common confusion: adding "sum of revenue" expecting the **raw total** of all revenue events across
exposed users. PostHog instead returns the **mean of per-user totals** — for each exposed user, sum
their revenue events, then average across users in the variant.

**Worked example:** user A spent $50, user B spent $10. PostHog reports `($50 + $10) / 2 = $30`, not
`$60`. The number looks much smaller than a raw SQL `SUM(revenue)` over the same time window
because it isn't a sum at all — it's the unit on which the statistical comparison runs.

This is the correct way to do statistical comparison (per-user values are the unit of randomization),
but it's a frequent source of "why is the number so much smaller than my SQL?" questions.

**Recommend:** explain the per-user aggregation. For a raw total for reporting, multiply the mean
by the user count, or use product analytics for the descriptive total.

## D5 — Property breakdowns silently return "none" for missing properties [MEDIUM]

If a user breaks down by a property that doesn't exist on the event being broken down, every value
shows as "none" rather than an error. This is silent and confusing.

**Verify:** check that the breakdown property is actually being captured on the relevant event.

**Recommend:** if it's the exposure event missing the property, see D3 — set the property earlier in
the journey, or capture it on `$feature_flag_called` directly.

## D6 — Recordings panel ≠ statistical calculation [MEDIUM]

The "View recordings" panel on the experiment page applies **metric events as filters** for finding
relevant replays — but those filters **don't map exactly to the statistical calculations** (e.g. funnel
attribution type isn't applied, conversion windows may not be).

**Implication:** the "story" in recordings can't be reconciled 1:1 with the computed result. Don't
debug stats discrepancies via the recordings panel.

**Recommend:** use recordings to _qualitatively_ understand variant differences (what users actually
experienced), not to _audit_ the numbers.

## D7 — Conversion-window anchoring (differs by metric type) [HIGH]

The conversion window isn't a single rule — the new query runner applies it differently per metric
type:

- **Mean / ratio metrics.** Events count when
  `timestamp >= first_exposure_time AND timestamp < last_exposure_time + conversion_window`. The
  _lower_ bound is anchored to the user's first exposure; the _upper_ bound is anchored to their
  _last_ exposure plus the window. Re-exposure extends the observation period; earlier conversions
  still count.

  <!-- Source for maintainers: _conversion_window_predicate in
  posthog/hogql_queries/experiments/experiment_query_builder.py (mean/ratio branch).
  The exposures CTE defines first_exposure_time = min(timestamp), last_exposure_time = max(timestamp). -->

- **Funnel metrics.** The conversion window is enforced _between consecutive funnel steps_ by the
  `aggregate_funnel_array` ClickHouse UDF — not as a single window from first exposure. Each new
  exposure event resets the funnel's step-0 anchor, so re-exposure _restarts_ the funnel rather than
  extending an existing attempt. Ordered funnels skip the SQL-level temporal filter entirely; the
  per-step gap check in the UDF is the only window enforcement.

  <!-- Source for maintainers: funnel-udf/src/steps.rs (per-event step-0 reset and the
  consecutive-step gap check). experiment_query_builder.py documents the ordered-vs-unordered
  branch. -->

**Implication for SQL reconciliation:**

- Mean/ratio reconciliation: gate with
  `e.timestamp >= u.first_exposure_time AND e.timestamp < u.last_exposure_time + INTERVAL '<window>'`,
  not a single window from first exposure.
- Funnel reconciliation: compute step-to-step gaps, not a single window from first exposure. A user
  who is re-exposed gets a fresh chance to complete the funnel — your SQL must allow this or
  PostHog's numbers will look larger than yours.

If the numbers shifted unexpectedly across a query-runner migration, this is the most likely cause:
historical pre-migration funnel attribution did not have the per-step gap semantics.

## D8 — Cached results can lag behind ingestion [HIGH]

Experiment results are cached for up to 24 hours. Force-refresh (the manual button on the page) bypasses
the cache. If pre-aggregation is enabled and a precomputation insert fails, PostHog falls back to a
real-time query — which can produce a small inconsistency between two consecutive views, especially on
fresh data.

**Recommend:** if numbers look stale, force-refresh the experiment first before debugging.

## D9 — Applying a filter doesn't change the user count [MEDIUM]

Symptom: a filter is added to a metric (e.g. "by device = mobile") and the exposure / user count
stays the same — only the conversion side moves. The conclusion looks like "the filter isn't
working."

The experiment's denominator is the **set of exposed users**, fixed at exposure time. A filter on a
property of the metric event acts as a _gate within that fixed population_ — it changes who counts
as converted, not who counts as in the experiment. The denominator correctly does not shrink.

To shrink the denominator (i.e. only count users who match the filter as part of the experiment at
all), **encode the eligibility upstream** — either in release conditions, or by setting the
property on the exposure event itself, or by using a custom exposure event that already filters.

**Recommend:** explain the scope difference. If the mental model comes from another A/B tool that
subset-filters the population on metric properties, name the tool and explain the design choice
explicitly.

## D10 — No "current person properties" toggle on experiment metrics [MEDIUM]

Insights have a "Use current person properties" toggle (versus as-of-event). Experiment metrics
**do not** expose this toggle — person properties are always evaluated as of the time the event was
captured.

This is intentional: the experiment's population needs to be stable across the run. If person
properties were re-resolved at query time, the population a user falls into could change over the
course of the experiment as their attributes change (plan upgrades, geo moves, etc.), which would
invalidate the analysis.

**Recommend:** for slices by "current state" attributes (e.g. "free vs paid as of today"), use one
of:

- A **dynamic cohort** for "currently paid" users, and target the experiment to that cohort via
  release conditions.
- A **HogQL expression** in the metric filter that joins person properties at query time, accepting
  that the answer reflects the current state, not the state at exposure.
- A **property captured on the exposure event** (e.g. plan tier at the time of exposure), so the
  slice is stable and analysable as a breakdown.

## D11 — Metric definition traps (empty event filter, HogQL count(boolean)) [HIGH]

Two `EventsNode`-shaped metric mis-configurations recur. Both produce numbers that look like
the data is broken but are actually the metric definition doing precisely what it was asked.

**`event: ""` is not "all events".** In an `EventsNode`, the `event` field is an _equality_ filter
against the event name. An empty string matches events literally named `""` — i.e. none. The
metric's `metric_events` CTE returns no rows, the LEFT JOIN from `exposures` produces NULLs on the
metric side, and the resulting metric collapses to a constant per user (commonly `1.0` for a
mean-shaped boolean count, or `0` for a `total` math). "All events" as a _user-facing_ concept
requires either no event filter at the metric source or a different metric kind — not `event: ""`.

**`count(boolean_expression)` counts non-null, not true.** A HogQL `math_hogql` of the form
`count(properties.X = 'value')` counts every event where the expression evaluates (i.e. every event
where the property is set, true or false), not events where the expression is true. Use
`countIf(properties.X = 'value')` for the "true" semantics, or `sum(toInt(properties.X = 'value'))`
for an additive form.

**Verify directly.** Inspect the rendered `clickhouse_sql` field from `experiment-results-get` —
the `metric_events` CTE shows the actual `WHERE` clause and the per-event `value` expression. If
the `WHERE` contains `equals(events.event, '')`, the metric is filtering to no events. If the
per-event `value` is a boolean expression wrapped in `count(...)`, the math is counting evaluations
not truths. Either signature is dispositive.

**Validation signals from PostHog.** A `validation_failures` entry of `"baseline-mean-is-zero"` on
a mean metric is the system's tell that _every_ exposed user contributed 0 to the metric — almost
always a `total` math on a never-matching event filter.

**Recommend:**

- Replace `event: ""` with the actual event to measure (or use a metric kind that genuinely means
  "all events" — confirm in the metric editor, not by typing `""`).
- For HogQL math: pick `countIf(...)` or `sum(toInt(...))` over `count(...)` of a boolean.
- Metric edits on a running experiment recompute the metric over the full duration. Flag this to
  the user before recommending so the post-edit numbers don't surprise them. Force-refresh the
  experiment page after saving.
