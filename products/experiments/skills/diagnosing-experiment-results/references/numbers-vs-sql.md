# PostHog numbers don't match the user's SQL / raw count

The experiment page applies a specific scope that ad-hoc SQL almost never replicates.
A common pattern: SQL is written "to verify" experiment numbers and the results don't match — most of
the time, the experiment numbers are correct and the SQL is missing one or more scope filters.
The same holds for an insight, a dashboard, another analytics tool, or an AI assistant that counted the events without the experiment's scope.

## Before walking this file

If the gap between **exposures and downstream metric counts** is very large (the metric is one or
two orders of magnitude smaller than exposures), don't anchor on SQL reconciliation. That shape of
divergence is most often a bucketing or identity-resolution problem, not a query-scope problem —
walk `bias-and-skew.md` first (especially A3 / A4) and only come back here once identity is ruled
out. The symptom often surfaces as "the numbers don't match", but the agent should route it to A
before D.

Check the age of the number before its scope: `query_to` in the stored results says what data the stored numbers cover, and D8 says when the page shows other numbers.

## Contents

- D1 — Scope mismatch checklist (the eleven sources)
- D2 — Funnel: only first→last step counts for stats
- D3 — Breakdowns read from the exposure event, not the metric event
- D4 — "Sum of revenue" = mean of per-user totals (not raw total)
- D5 — Property breakdowns silently return "none" for missing properties
- D6 — Recordings tab ≠ statistical calculation
- D7 — Conversion-window anchoring (differs by metric type)
- D8 — Cached and stored results can lag behind ingestion
- D9 — Applying a filter doesn't change the user count
- D10 — No "current person properties" toggle on experiment metrics
- D11 — Metric definition traps
- D12 — The experiment counts a wider population than the insight it is compared with
- D13 — A metric's title does not match what it measures

## D1 — Scope mismatch checklist (the eleven sources) [HIGH]

When the user reports "PostHog says X, my SQL says Y", walk this checklist.
Every item is readable from `experiment-get`, with two exceptions: the rows of the project's test-account filter are in `project-get`, and CUPED falls back to the project default when the experiment does not set it (C13 in `interpretation.md`):

1. **Exposure scope.** The experiment counts only events that occur at or after the user's first exposure.
   Raw counts don't filter this way.
2. **`$multiple` exclusion.** With default handling (`exclude`), multi-variant users are dropped from
   metrics. Raw counts include them.
   No event carries `$multiple`: it is computed per person.
3. **Test-account filter.** Defaults to `true` — internal/test users excluded. Raw counts don't
   typically apply it.
4. **Date range.** Exposures are bounded by `start_date` / `end_date`; raw counts often span more.
   Metric events of an exposed person count beyond `end_date` while that person's conversion window is open (D7).
5. **Variant attribution.** The experiment takes the variant from the _exposure event_, and only when it is one of the flag's variant keys and not listed in `excluded_variants`.
   A flag property on a metric event plays no role (B11 in `empty-experiment.md`).
6. **Conversion window.** For every metric type, events outside the per-user conversion window are not
   counted. See D7.
7. **Per-user aggregation.** Mean metrics aggregate per-user before averaging, so the result is
   not a raw event-level total. See D4.
   A ratio metric divides the sum of the per-person numerators by the sum of the per-person denominators: these are totals inside the experiment's scope, so its gap to raw SQL comes from the other sources.
8. **Outlier handling (winsorization).** Mean metrics can clamp per-user values at a lower and an upper percentile before averaging.
   Ratio metrics can clamp numerator and denominator separately.
   With a breakdown, the thresholds are computed per breakdown group.
   When enabled, no raw SQL `AVG`/`SUM` over the underlying events will reconcile — values are post-clamp.
9. **CUPED.** With CUPED on, the effect and its interval of a mean metric or an ordered funnel come from adjusted values (C13 in `interpretation.md`).
   Ratio and retention metrics are never adjusted, and neither is a mean with a threshold or on a session property, or a funnel with a data warehouse step.
10. **Completed windows only.** With `only_count_matured_users` on (the setting "Require completed conversion or retention window"), people whose conversion window has not elapsed between their first exposure and the time of the calculation are left out.
    A metric without a conversion window leaves no one out.
    A retention metric uses the end of its retention window instead, measured from its start event. See E11 in `mid-run-changes.md`.
11. **The unit.** A group-aggregated experiment counts groups, not people, and drops exposure and metric events that carry no group key, or a key in another spelling or case.

<!-- Source for maintainers (may rot): ExposureQueryBuilder in
products/experiments/backend/hogql_queries/experiment_exposure_query_builder.py; build_metric_predicate and
build_conversion_window_predicate_for_events in experiment_metric_values.py; build_mean_query_with_winsorization in
experiment_mean_query_builder.py; build_ratio_query_with_winsorization in experiment_ratio_query_builder.py. -->

**Recommend:** reproduce the experiment's scope in SQL exactly (start with `experiment-get`'s
`exposure_criteria`, `metrics`, and `stats_config`), or accept that ad-hoc SQL will not match by
design.

### Canonical scope-reproducing HogQL skeleton

Use this as the starting point when the user wants to reconcile. Fill the placeholders from
`experiment-get`. It reproduces sources 1, 2 and 7 directly, source 6 with the line noted inline, and sources 4 and 5 only with the notes below.
Sources 3, 8, 9, 10 and 11 are not in it, and neither are the property filters of the exposure criteria and of the metric: say which of them the experiment uses, because each one alone explains a gap.

It follows the query rules in `diagnostic-snapshot.md`.
A run of months is a scan of months.
Reconcile the first week of the run first: set `<window_start>` to the experiment's `start_date`, and compare with the value of the window's last day in the metric's daily series (`experiment-timeseries-results`, with the metric's `uuid` and `fingerprint` from `experiment-get`).
The daily series is cumulative from the start date, so a later week alone does not compare with it.
Set `<window_end>` to the end of that day in the project's time zone, written in UTC: the series keys each point by the day on which its data ends.
A point can end earlier on that day, at the time it was computed, and then holds only the metric events that had arrived by then.
The series does not say when a point was computed: a gap that the last day or the conversion window explains does not point to a scope difference.
Widen only when the first week matches.

```sql
SELECT
    variant,
    count() AS exposed_persons,
    countIf(metric_events_counted > 0) AS persons_with_metric,
    sum(metric_events_counted) AS metric_events,
    avg(metric_value) AS mean_value_per_person
FROM (
    SELECT
        person_id,
        -- source 2, exclude handling: a person with more than one variant key becomes $multiple
        if(
            uniqIf(properties.$feature_flag_response, event = '<resolved_exposure_event>') > 1,
            '$multiple',
            anyIf(properties.$feature_flag_response, event = '<resolved_exposure_event>')
        ) AS variant,
        minIf(timestamp, event = '<resolved_exposure_event>') AS first_exposure,
        -- source 1: only metric events at or after the first exposure
        -- source 6: with a conversion window, also x.1 < first_exposure + toIntervalSecond(<window_seconds>)
        arrayFilter(
            x -> x.1 >= first_exposure,
            groupArrayIf(
                (timestamp, coalesce(toFloat(properties.`<value-property>`), 0)),
                event = '<metric-event>'
            )
        ) AS counted,
        length(counted) AS metric_events_counted,
        -- source 7: one value per person first, then the mean across people
        arraySum(arrayMap(x -> x.2, counted)) AS metric_value
    FROM events
    WHERE timestamp >= toDateTime('<window_start>', 'UTC')   -- source 4
      AND timestamp < toDateTime('<window_end>', 'UTC')      -- source 4
      AND (
          event = '<metric-event>'
          OR (
              event = '<resolved_exposure_event>'
              AND properties.$feature_flag = '<flag-key>'
              -- source 5: only the flag's variant keys are exposures
              AND properties.$feature_flag_response IN ('<variant-key-1>', '<variant-key-2>')
          )
      )
    GROUP BY person_id
    HAVING countIf(event = '<resolved_exposure_event>') > 0
)
GROUP BY variant
ORDER BY variant
```

Notes:

- **The `$multiple` row** is the people the experiment excludes. Leave it out of the comparison.
- **`multiple_variant_handling = 'first_seen'`**: replace the `variant` expression with
  `argMinIf(properties.$feature_flag_response, timestamp, event = '<resolved_exposure_event>')`.
- **A custom exposure event** has no `$feature_flag` property: filter on its event name only, and read the variant from `` properties.`$feature/<flag-key>` ``.
- **An activation event** (`exposure_criteria.activation_config`): the experiment counts a person only from the first activation event at or after the first flag exposure.
  The skeleton does not reproduce that: it counts everyone with a flag exposure, from the flag exposure.
- **Excluded variants** (source 5): list in the `IN` clause only the flag's variant keys that are not in `excluded_variants`.
- **Property filters in the exposure criteria** (`exposure_criteria.exposure_config.properties`): the experiment counts only the exposure events that match them, for the default exposure event as for a custom one.
  Add the same conditions to the exposure branch of the `WHERE` clause.
- **Metric events after `<window_end>`** (source 4): the experiment reads exposures up to and including `<window_end>`, and a person's metric events up to `<window_end>` plus the conversion window.
  The skeleton cuts both at `<window_end>`, so a person exposed near the end loses the conversions after it.
  To match, replace the second `timestamp` bound with `timestamp < toDateTime('<window_end>', 'UTC') + toIntervalSecond(<window_seconds>)`, and add `AND timestamp <= toDateTime('<window_end>', 'UTC')` to the exposure branch.
  Without a conversion window, `<window_seconds>` is 0.
- **A group-aggregated experiment** (source 11, `feature_flag.filters.aggregation_group_type_index` in `experiment-get`): the skeleton counts people.
  Replace `person_id` with `` `$group_<index>` `` in the inner `SELECT` and `GROUP BY`, and add ``AND `$group_<index>` != ''`` to the `WHERE` clause.
- **The metric's own definition:** add the metric's property filters to both `<metric-event>` conditions, and for a metric on an action use the action's conditions in place of the event name.
  Math other than a count or a sum needs its own per-person aggregate in place of `arraySum`.
  The skeleton does not cover retention metrics.
- **Funnel metrics** (D2): only the first-step → last-step conversion counts for stats.
  Put the funnel's last step in `<metric-event>` and read `persons_with_metric / exposed_persons`.
  Without a conversion window, that matches the experiment for a one-step funnel.
  With more steps the skeleton counts people the experiment does not, because it checks neither the presence nor the order of the intermediate steps.
  With a conversion window the skeleton measures it from the first exposure only, where the experiment starts a new attempt at each exposure (D7): a person who converts inside the window of a later exposure counts in the experiment and not in the skeleton.
- **"Sum of revenue"** (D4): `mean_value_per_person` is the experiment's number. A count metric is `sum(metric_events) / exposed_persons`.
- **Breakdowns** (D3): the breakdown value is the property on the person's first exposure event, not on the metric event.
- **Test-account filter** (source 3): the skeleton includes internal and test users.
  The experiment's count per variant is `number_of_samples`: in the stored results (`diagnostic-snapshot.md`) for a window that ends at their `query_to`, and in the daily series for a window that ends on that point's day.
  For a retention metric with its own start event, `number_of_samples` counts only the people who did that event: read it from a mean, ratio or funnel metric of the same experiment.
  A gap between that and `exposed_persons` is the filter, when no exposure filter, excluded variant, group unit or completed-window setting is in play.

## D2 — Funnel: only first→last step counts for stats [HIGH]

For multi-step funnel metrics, **statistical significance is always calculated between the first
step (exposure) and the final step**. Intermediate steps are shown for analysis and visualization
but **do not affect the significance calculation nor win probability** — a user can read a significant intermediate
step and incorrectly conclude the whole funnel is significant.

**Implication:** comparing PostHog's funnel conversion rate to a SQL query that counts intermediate
conversions will not match — and that's expected.
A difference in the rate of one step after the split is not a result either: that step's rate counts only the people who reached the step before it, and those groups are no longer comparable between the arms.

The exposure event is automatically prepended as `step_0` for funnel metrics, so a 1-step funnel is
really a 2-step funnel: **exposure → action**. Conversion = % of exposed users who reached the action.

## D3 — Breakdowns read from the exposure event, not the metric event [HIGH]

When a user adds a breakdown (e.g. "by country" or "by device type") to an experiment metric, the
property is read from the **exposure event**, not the metric event: each person gets the value on their first exposure.
This is for statistical reasons —
the metric event happens after exposure, but the breakdown needs to partition users at the time of
exposure.

**Implication:** if the property only exists on the metric/conversion event (e.g. a checkout event with
`payment_method`), breaking down the experiment by it won't work — every user will appear under "none"
because the property isn't on the exposure event.

**A property the treatment can change** `[MEDIUM]`.
The breakdown splits the denominator too: each slice holds the people whose first exposure carried that value.
That is sound for a stable property (country, plan at exposure).
For a property that the variant itself influences (which mode or page the person entered first), the slices differ between the arms in who is in them, and a per-slice comparison is biased.
Use a metric filtered to the slice in place of the breakdown: the numerator is filtered and the denominator stays every exposed person (D9).
A retention metric with its own start event is the exception: its denominator is the people who did the start event, so a filter on the start event filters the denominator too.

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

Metric types count different units.
A ratio metric divides the sum of one per-person value by the sum of another: with count math, a total of events by a total of events.
A one-step funnel counts people.
The same event under two metric types gives two numbers, and both are right.

**Recommend:** explain the per-user aggregation. For a total for reporting, multiply the mean
by the user count, or use product analytics for the descriptive total.
The product is the total inside the experiment's scope (D1): events after each person's first exposure and inside the conversion window, of the people the experiment counts, after any outlier clamp.

## D5 — Property breakdowns silently return "none" for missing properties [MEDIUM]

If a user breaks down by a property that doesn't exist on the event being broken down, every value
shows as "none" rather than an error. This is silent and confusing.

**Verify:** check that the breakdown property is actually being captured on the relevant event.

**Recommend:** if it's the exposure event missing the property, see D3 — set the property earlier in
the journey, or capture it on the exposure event directly.

## D6 — Recordings tab ≠ statistical calculation [MEDIUM]

The experiment's Recordings tab, and the "View recordings" button on a variant's result row that opens it, list sessions of the people the experiment counts as exposed.
The metric filters there ("Fired all", "Fired any", "Fired none", "Finished funnel", "Didn't finish funnel", and "Fired <event>" or "Didn't fire <event>" on a result row) select sessions by the metric's events, one session at a time.
A session counts as fired when it holds one of the metric's events, or the first event of each metric when several metrics are selected under "Fired all".
The two funnel filters read only the funnel's last step.
They **don't map exactly to the statistical calculations**: no conversion window, no aggregation, and a funnel counts as finished on the last step's event.

**Implication:** the "story" in recordings can't be reconciled 1:1 with the computed result. Don't
debug stats discrepancies via the Recordings tab.

**No recordings for an exposed person** `[MEDIUM]`.
An exposure that a server sends carries no session id, or one that matches no recording, so no recording can be tied to the exposure event itself.
The person's other sessions can still have recordings, when replay is on for the project and the session was sampled. Find them by person, or by the flag's value on the session's events.

**Recommend:** use recordings to _qualitatively_ understand variant differences (what users actually
experienced), not to _audit_ the numbers.

## D7 — Conversion-window anchoring (differs by metric type) [HIGH]

Mean, ratio and retention metrics anchor the conversion window on the person's **first exposure**. A funnel anchors each attempt on its own exposure event:

- **Mean / ratio metrics.** Events count when
  `timestamp >= first_exposure AND timestamp < first_exposure + conversion_window`.
  A later exposure of the same person extends nothing.
  Without a conversion window there is no upper bound except the end of the experiment: a person who converts 45 days after exposure counts like one who converts in 5 minutes, and people exposed early have had more time than people exposed yesterday.
- **Funnel metrics.** Each step must happen within the window, measured from the exposure step, not from the step before.
  A later exposure event starts a new attempt with its own window, and the furthest step the person ever reached is what counts.
  An unordered funnel needs all its steps, the exposure included, within one window of each other, in any order.
- **Retention metrics.** A custom start event must occur within the conversion window after the first exposure, when one is set (E10 in `mid-run-changes.md`).
  Retention windows in days or hours compare calendar days or hours in the project's time zone, not exact 24-hour periods.
  Windows in weeks, months, minutes or seconds compare exact timestamps.

**The window runs past the end date.**
With a 7-day window, a person exposed on the last day counts conversions for 7 more days.
The stored results of an ended experiment can lack them, because its calculation is tied to the end date (D8).

<!-- Source for maintainers (may rot): build_conversion_window_predicate_for_events and build_metric_predicate in
products/experiments/backend/hogql_queries/experiment_metric_values.py; funnel-udf/src/steps.rs (each step keeps the
timestamp of the first step); build_start_after_exposure_predicate in experiment_retention_query_builder.py. -->

**Implication for SQL reconciliation:**

- Mean/ratio reconciliation: gate with one window from the first exposure.
  A query that extends the window from the last exposure counts more than PostHog does.
- Funnel reconciliation: every step within one window from the exposure.
  A user who is re-exposed gets a fresh chance to complete the funnel — your SQL must allow this or
  PostHog's numbers will look larger than yours.

Part of the public docs still describes the window of mean metrics as extended by a later exposure.
The rule above is the one the results use.

## D8 — Cached and stored results can lag behind ingestion [HIGH]

The numbers on the page are a stored calculation, not a live query.
The exception is a project that the stored calculation is not rolled out to: there the page runs one query per metric and keeps each result for up to 24 hours, and `query_to` says nothing about what the user sees.
No tool says which of the two a project has.

**Evidence.** `experiment-metrics-recalculation-latest-retrieve` returns `query_to`: the end of the data the stored numbers cover.
Compare it with now, and with the time of the events the user expects to see.

What makes a number old:

- **The schedule.** Stored results are refreshed by a scheduled calculation, once a day by default.
  It takes a running experiment whose flag is on, that started between 12 hours and about two months ago, and that has at least 50 exposures in total.
  A paused experiment, a small one and one that has run for more than about two months get no scheduled calculation.
  The schedule is a rollout: where it is off, the stored results change only when someone refreshes on the page, edits the experiment there, or starts a calculation.
  So read `query_to`, and do not assume a daily refresh.
- **The cache.** A result computed on demand is kept for up to 24 hours.
  `refresh: true` on `experiment-results-get` does not force a new calculation.
  With or without it, the call returns a cached result that is younger than 24 hours, and computes when there is none.
- **A stopped experiment.** A calculation that runs after the stop ends at the end date.
  Every later one finds that result and reuses it without a query: the same "last refreshed" time, the same numbers.
  A refresh then brings in nothing new.
  Only a change of the metric, the exposure criteria, the method, the start date, the excluded variants or the completed-window setting computes again. A change of the confidence level, of CUPED, of sequential testing or of the baseline does not.
  When no calculation ran after the stop, the stored results end at the last one before it, and `query_to` lies before `end_date`.
  The numbers then miss the last hours, or more, of the run.
  Conversions that arrived after the calculation, inside a window that was still open, stay out of the stored numbers (D7).
- **Late or backfilled events.** A project with precomputed results keeps each day's exposures and metric events once that day is a few days old.
  Events that arrive later for that day stay out of the results for about two months.
  `is_precomputed: true` on a metric's stored result says that the project precomputes and that this metric's exposures were read from that store.
- **A removed variant.** Results computed before a variant left the flag keep that variant until the next calculation: up to 24 hours for a cached result.
- **A changed setting.** An edit of a metric, of the exposure criteria or of a statistics setting on the page recalculates the whole run.
  Numbers that moved without new data are usually this: read `experiment-activity`.
  An edit through the API or a tool starts no calculation.
  The stored results of the changed metrics then come back empty until someone opens the page or a calculation runs.

Whatever the cause, a `query_to` far behind now on a running experiment, or far behind `end_date` on a stopped one, means that the stored numbers are old.
Say how old before you interpret them.

A failed calculation is not a zero.
A metric whose stored result has `status: failed` shows no value on the page (see "Metric rows with `data: null`" in `diagnostic-snapshot.md`).

**Recommend:** state `query_to` with every number you take from the stored results.
When the user needs current numbers, the refresh control on the page recalculates, and so does `experiment-metrics-recalculation-create`: ask first, because it computes every metric.
An ended experiment has no refresh control on the page: the tool is the way to compute up to the end date.
On a stopped experiment that already has a calculation after the stop, neither brings in new data.

## D9 — Applying a filter doesn't change the user count [MEDIUM]

Symptom: a filter is added to a metric (e.g. "by device = mobile") and the exposure / user count
stays the same — only the conversion side moves. The conclusion looks like "the filter isn't
working."

The experiment's denominator is the **set of exposed users**, fixed at exposure time. A filter on a
property of the metric event acts as a _gate within that fixed population_ — it changes who counts
as converted, not who counts as in the experiment. The denominator correctly does not shrink.
A retention metric with its own start event is the exception: its denominator is the exposed people who did the start event, so a filter on the start event shrinks it.

To shrink the denominator (i.e. only count users who match the filter as part of the experiment at
all), **encode the eligibility upstream** — in release conditions, in a property filter on the exposure criteria (B12 in `empty-experiment.md` lists what such a filter can read), or with a custom exposure event that already filters.

**Recommend:** explain the scope difference. If the mental model comes from another A/B tool that
subset-filters the population on metric properties, name the tool and explain the design choice
explicitly.

## D10 — No "current person properties" toggle on experiment metrics [MEDIUM]

Insights have a "Use person properties from query time" toggle (versus as-of-event). Experiment metrics
**do not** expose this toggle.
They read person properties in the project's person-properties mode: the value as of the time the event was captured when the project keeps person properties on events, the person's current value when it joins them at query time.
Which of the two applies differs between projects.

This is intentional: the experiment's population needs to be stable across the run. If person
properties were re-resolved at query time, the population a user falls into could change over the
course of the experiment as their attributes change (plan upgrades, geo moves, etc.), which would
invalidate the analysis.

**A property that was set or backfilled after the events** is therefore invisible to a breakdown or a filter when the project keeps person properties on events: the old events keep the old value.
A person property synced from a data warehouse behaves the same way.

**Recommend:** for slices by "current state" attributes (e.g. "free vs paid as of today"), use one
of:

- A **HogQL expression** in the metric filter that reads the person's current properties (`pdi.person.properties.<key>`), accepting
  that the answer reflects the current state, not the state at exposure.
  Plain `person.properties.<key>` reads the value on the event when the project keeps person properties on events, and the current value otherwise.
  One filtered metric per slice replaces the breakdown.
- A **property captured on the exposure event** (e.g. plan tier at the time of exposure), so the
  slice is stable and analysable as a breakdown.
- A **dynamic cohort** for "currently paid" users in the flag's release conditions, before launch.
  Do not use a dynamic cohort in the exposure criteria to mirror a release condition: the two are evaluated at different times (A7 in `bias-and-skew.md`).

## D11 — Metric definition traps [HIGH]

Metric configurations that produce numbers which look like broken data and are the definition doing exactly what it says.
Each is readable from the metric's definition in `experiment-get`.

**`event: ""` is not "all events".** In an `EventsNode`, the `event` field is an _equality_ filter
against the event name. An empty string matches events literally named `""` — i.e. none. The
metric collapses to a constant per user (commonly `0`).
A mean or ratio metric left on the editor's "All events" placeholder is the same case: the editor stores the name `All events`, which matches no event, and the page rejects such an inline metric on save (next paragraph).
A funnel step left on "All events" is the opposite: it is stored without an event name and counts every event.
In a ratio metric the two halves can differ: an empty-string numerator matches nothing, and a denominator without an event counts every event.

**An event the project has never received.**
A misspelled or not-yet-shipped event name gives a metric that is 0 in every variant.
Inline metrics are checked against the project's events when they are saved, unless the caller passed `allow_unknown_events`.
Shared metrics are not checked.
_Evidence:_ the event name is absent from the project's event definitions.

**`count(boolean_expression)` counts non-null, not true.** A HogQL `math_hogql` of the form
`count(properties.X = 'value')` counts every event where the expression evaluates (i.e. every event
where the property is set, true or false), not events where the expression is true. Use
`countIf(properties.X = 'value')` for the "true" semantics, or `sum(toInt(properties.X = 'value'))`
for an additive form.

**An upper outlier bound on a rare event.**
With an upper percentile set and `ignore_zeros` off, the percentile is taken over all exposed people.
When most people have a value of 0, the bound itself is 0 or close to it, and every value is clamped down to it: the metric shows no difference, or a difference that is an artifact of the clamp.
_Evidence:_ `upper_bound_percentile` on a mean metric (or on a ratio's numerator or denominator) with `ignore_zeros` false, and a metric event that few exposed people send.
_Fix:_ turn on `ignore_zeros`.

**An event that only one variant sends** `[LOW]`.
When each arm reports its conversion with its own event and the metric names one of them, one arm cannot convert.
The lift is enormous or undefined.
_Fix:_ one action that covers both events, used as the metric.

**Validation signals from PostHog.** A `validation_failures` entry of `"baseline-mean-is-zero"`
is the system's tell that the baseline variant's values sum to 0 (for a ratio, its numerator).
For a metric whose values cannot be negative, _every_ person in the baseline variant contributed 0 to the metric — almost
always one of the traps above.
With it, no test variant gets an effect or an interval.

**Verify directly.** Read the metric's definition: `source`, `series`, `numerator`, `denominator`, the math and the outlier settings.
The generated SQL is not part of the results an agent can read.

**Recommend:**

- Replace `event: ""` with the actual event to measure.
- For HogQL math: pick `countIf(...)` or `sum(toInt(...))` over `count(...)` of a boolean.
- Metric edits on a running experiment recompute the metric over the full duration (D8 says when). Flag this to
  the user before recommending so the post-edit numbers don't surprise them.

## D12 — The experiment counts a wider population than the insight it is compared with [MEDIUM]

**Symptom (in the user's vocabulary):** "the experiment says flat, our dashboard shows a clear drop", "the conversion rate in the experiment is half of what the funnel shows", "most of the exposed users are existing customers".

**Behavior.** The experiment counts everyone who was exposed.
The team's own funnel or dashboard often counts a narrower group: new visitors only, verified sign-ups only, one surface only.
When the change targets that narrow group and the flag is evaluated for everyone, the people the decision is about are a small share of the exposed, and their effect is diluted or reversed in the experiment's number.
The exposure settings look correct, because they are the defaults. The mismatch is between the exposed population and the population the decision is about.

**Evidence to gather.**

- **The reference.** The insight the user trusts: its filters on persons and events (`insight-get`), and its numbers (`insight-query`).
  When the user names none, ask which funnel or dashboard the team decides by.
  Do not pick one for them.
- **The experiment.** `exposure_criteria` and the flag's release conditions: is there a filter that keeps the same people out?
- **The difference,** listed filter by filter.
  Typical: existing users in an acquisition experiment, unverified or bot sign-ups, a flag that is read on more pages than the one under test, a second experiment on the same surface (the `finding-experiments` skill lists the project's experiments by date and flag).

The reverse case, an insight that counts more than the experiment because nothing scopes it to exposed people, is D1.

**MUST compare the exposed population with the population the decision is about before calling the setup sound.**

**MUST NOT conclude that exposure is fine because the exposure criteria are the defaults.**
The defaults say how exposures are counted, not who should be in the experiment.

**Co-occurs with:** B9 in `empty-experiment.md`, C12 in `interpretation.md`, D1.

**Recommendation.** Narrow the experiment to the people the decision is about: a release condition, a filter in the exposure criteria, or an exposure event at the point of the change.
On a running experiment this is a mid-run change (E5 in `mid-run-changes.md`): an exposure-criteria filter recomputes the whole run (D8 says when) and moves no one between variants, a release condition changes who enrolls from now on.
State the trade-off, and let the user choose between narrowing in place and a clean restart.

## D13 — A metric's title does not match what it measures [MEDIUM]

**Symptom (in the user's vocabulary):** "the metric is called 7-day retention and the number makes no sense", "the sign-up metric counts something else", a result that contradicts the same-named insight.

**Behavior** `[HIGH]`. A metric's name is free text.

- A typed name is never updated when the metric's events, math or windows change.
  It can describe an earlier definition.
- A metric without a typed name shows a title derived from its events: the first event of a mean or a funnel, numerator and denominator of a ratio, start and completion event of a retention metric.
- A shared metric shows the name of the shared metric.
  An edit of a shared metric changes it in every experiment that uses it, finished ones included.

**Evidence to gather.** For each metric the user reads: the name, then `metric_type` and the definition (`source` or `series`, `numerator` and `denominator`, `start_event` and `completion_event`, the conversion or retention window, the math).
For a shared metric, also the experiment's change history: was the shared metric edited during the run?

**MUST say what the metric measures now, from its definition, when the title and the definition disagree.**

**MUST NOT restate the title as the definition.**
A result explained by its title is wrong whenever the two differ.

**Co-occurs with:** D11, E6 and E10 in `mid-run-changes.md`.

**Recommendation.** Rename the metric to what it measures, or correct the definition.
A definition change recomputes the metric over the whole run (D8 says when).
