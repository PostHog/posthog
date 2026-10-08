# Diagnostic snapshot

Before asking clarifying questions, gather evidence directly.
Most diagnostics in this skill can be confirmed or ruled out from data, and a question to the user is the fallback for what the tools cannot answer.

Read in the order below.
Each step costs more than the one before, and most diagnostics are settled by the first three.
Run the snapshot once and reuse the results across the dispatch table in `SKILL.md`.

| Step | Read                                                               | Cost                                                                     |
| ---- | ------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| 1    | Configuration: `experiment-get`                                    | One read                                                                 |
| 2    | Stored results: `experiment-metrics-recalculation-latest-retrieve` | One read, never starts a calculation                                     |
| 3    | Changes: `experiment-activity`                                     | One read                                                                 |
| 4    | Exposure data: `experiment-results-get`                            | Runs the exposure query and every metric query that has no cached result |
| 5    | Raw exposure events: `execute-sql`                                 | A scan of events. Only for what steps 1 to 4 cannot show                 |

## Stored results

Powers the C and D groups, and every question about how fresh a number is.

`experiment-metrics-recalculation-latest-retrieve` returns the last finished calculation, including one in which some metrics failed: one entry per metric with the per-variant statistics, and for the run:

- **`query_to`** — the data the numbers were computed against ends here.
  State it when you report a number.
  A calculation that runs after the experiment stopped ends at the end date.
  When the last calculation ran before the stop, `query_to` lies before `end_date`, by hours or by weeks, and the stored numbers miss the time between (D8 in `numbers-vs-sql.md`).
  Compare the two on every stopped experiment.
- **`number_of_samples`** per variant — the units the metric counts as exposed.
  It gives the observed split without another call.
  It leaves out the units counted as `$multiple` and, when `only_count_matured_users` is on, the units whose metric window has not ended yet: it can be lower than the exposure counts, and it can differ between metrics.
  The stored results carry no `exposures` object: the count of people in several variants, the p-value of the sample ratio test and the daily series come from the exposure data below.
- **`result_source`** — `recalculation` for a real run.
  `timeseries_fallback` means that no run has completed and the numbers are a placeholder built from the daily series: say so.
- **`active_run`** — present while a run executes.
  The results returned are those of the run before.
  When no run has finished yet, they are the `timeseries_fallback` placeholder, or the running calculation itself: its `status` is `pending` or `in_progress`, and its `results` are empty or partial.
- **404** — no results yet. The experiment has not run long enough, or was never calculated.
- **A metric with `status: failed`** carries its `error_message`.
  That is a failed computation, not a result of zero.
- **An empty `results`, or a metric that is missing from it.**
  The start date, the exposure criteria, the method, the excluded variants or the completed-window setting changed after the run, or the metric was added or edited after it.
  The stored rows no longer match the experiment and are left out until the next calculation (D8 in `numbers-vs-sql.md`).
  That is not a result of zero either.

A variant's result can carry `validation_failures`.
The variant then has no chance to win, no p-value and no significance.
A failure on the baseline leaves every variant without them:

| Value                    | Rule                                                                                                     |
| ------------------------ | -------------------------------------------------------------------------------------------------------- |
| `not-enough-exposures`   | Fewer than 50 exposures in the variant                                                                   |
| `not-enough-metric-data` | Funnel or retention metric: fewer than 5 conversions in the variant. Ratio metric: a denominator of zero |
| `baseline-mean-is-zero`  | The baseline variant's total is 0 (D11 in `numbers-vs-sql.md`)                                           |

<!-- Source for maintainers (may rot): validate_variant_result in
products/experiments/backend/hogql_queries/utils.py. Verify before citing. -->

MUST read stored results before any tool that computes.
MUST NOT start with a tool that computes: `experiment-results-get` runs every metric query that has no cached result, and `experiment-metrics-recalculation-create` starts a calculation.
Ask the user before starting a recalculation, and say that it recomputes every metric.

## Exposure data

Powers A1, A2, A3, A7b, B0, C2 and the plateau check in `empty-experiment.md`.

`experiment-results-get` returns an `exposures` object next to the metric results.
Call it when the diagnosis needs one of the values below.
A split that the stored results already show as close to the configured one, on a complaint that is not about bias, does not need it.
It is the experiment's own exposure query: the experiment's exposure event, current variant keys only, the test-account filter, the experiment's window, each person counted once at the first exposure.
Variants in `excluded_variants` are left out of it, and on a group-aggregated flag it counts groups in place of persons.
With an activation event (`exposure_criteria.activation_config`) it counts a person only from the first activation event at or after the first flag exposure, at the time of that event.
The raw exposure queries below do not apply the activation event: they show the flag's calls.

- **`exposures.total_exposures`** — people per variant.
  The key `$multiple` holds the people who were exposed to more than one variant under `exclude` handling.
  Under `first_seen` handling the key is absent.
- **`exposures.sample_ratio_mismatch`** — `p_value` and the expected counts of the sample ratio test (A2). Null below 100 exposures.
- **`exposures.bias_risk`** — present when the bias banner's conditions hold, with `multiple_variant_percentage` (A1).
- **`exposures.timeseries[].exposure_counts`** — per variant, **cumulative** people by the day of their first exposure.
  A flat tail means no new people entered.
  It does not show whether the application still calls the flag: already-exposed people who return add nothing.
- **`exposures.date_range`** — the window the counts cover.

Read off:

- **Total exposures** — 0 means walk the B series. Under 50 in a variant, no result is computed for it (C2).
- **`$multiple` share** — non-zero brings A1, A3 and A4 onto the table.
- **Observed split against the configured split** — judge it by the p-value, not by eye (A2).
- **The daily series** — a gap between the arms that grows in one direction (A9), an arm that stops growing (A7b, A6), all arms flat (the closing section of `empty-experiment.md`).

Three properties of this tool:

- **It sends every metric query of the experiment in one call.**
  A query with a result younger than 24 hours is answered from the cache. The rest run.
  On an experiment with many or heavy metrics that is slow, and metric rows can fail (see "Metric rows with `data: null`").
  Call it once per diagnosis.
- **`refresh: true` does not force a recomputation.**
  Results younger than 24 hours come from the cache with or without it.
  `last_refresh` and `is_cached` on each row say how old a number of this tool is.
  `query_to` dates the stored results, which are another store.
- **Its `experiment.status` is derived from the dates only** (`draft`, `running`, `completed`).
  Read `paused` and `exposure_frozen` from `experiment-get`.

<!-- Source for maintainers (may rot): ExperimentExposuresQueryRunner in
products/experiments/backend/hogql_queries/experiment_exposures_query_runner.py; getExposures and getMetricResults in
services/mcp/src/api/client.ts (refresh is sent as 'blocking', the API's default mode); transformExperimentResults in
services/mcp/src/schema/experiments.ts. -->

## Raw exposure events

Steps 1 to 4 say how many people the experiment counts.
Raw events say what the application sent: responses that are no variant, the library, the identifier, the time of the last event.
Query them when a diagnostic asks for exactly that.

### Query rules

Every query in this skill follows them.

- **One event name.** For the default exposure: the experiment's `resolved_exposure_event` from `experiment-get`.
  Do not hardcode `$feature_flag_called`.
- **Both ends of the time range**, at most 7 days per query, and one day first on a large project.
  The whole run of an experiment can be months of events.
  A property that is not a materialized column makes every row expensive: keep such a query to one day.
- **`toDateTime('<timestamp>', 'UTC')` for every timestamp.**
  A bare datetime string is read in the project's timezone, which moves the window by the project's offset.
- **The flag's variant keys**, from `feature_flag.filters.multivariate.variants[].key`, wherever a query counts people per variant.
- **The experiment's unit.**
  The queries count persons.
  When the flag is aggregated by a group type (`feature_flag.filters.aggregation_group_type_index` is set), count `$group_<index>` in place of `person_id` and leave out the rows where it is empty.
  A count of persons on such an experiment is not comparable with its exposures.
- **No test-account filter.**
  These queries include internal and test users, and the experiment's own numbers usually do not.
  Say so when the two are compared.
- **The exposure property filters.**
  When `exposure_criteria.exposure_config.properties` is set, the experiment counts only the exposure events that match them (B12).
  Add the same conditions to the `WHERE` clause, or say that the query counts more events than the experiment.

### Which event, which property

| `exposure_criteria.exposure_config`         | Event to query                                                    | Variant is in                                                 |
| ------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------- |
| Not set, or it names `$feature_flag_called` | `resolved_exposure_event`                                         | `$feature_flag_response`, with `$feature_flag` = the flag key |
| It names `$experiment_exposure`             | `$experiment_exposure`, whatever `resolved_exposure_event` says   | `$feature_flag_response`, with `$feature_flag` = the flag key |
| Any other event                             | That event                                                        | `` `$feature/<flag-key>` ``                                   |
| An action                                   | Every event that the action matches: read the action's definition | `` `$feature/<flag-key>` ``                                   |

The default event depends on two conditions.
It is `$experiment_exposure` when the experiment started on or after 2026-09-01 (UTC) **and** the project is in the rollout of that event.
Otherwise it is `$feature_flag_called`.
`resolved_exposure_event` already holds the answer: read it, do not derive it.

`$experiment_exposure` is a copy of `$feature_flag_called`, written at ingestion with the same properties.
It is written for every string response other than `true`, `false` and the empty value: a variant key, and also `holdout-<id>` or a key in another spelling.
A response of `true`, `false` or an empty value has no copy.
So a question about responses that are no variant (A10 in `bias-and-skew.md`) needs `$feature_flag_called`.

The copy is switched on per project, apart from the setting that makes an experiment read it.
When `resolved_exposure_event` is `$experiment_exposure`, that event has no rows for the flag, and `$feature_flag_called` has variant responses in the same window, the copy is not written for the project.
That is not a fault of the SDK or of the application: say so, and point the user to PostHog support.

<!-- Source for maintainers (may rot): resolve_default_exposure_event and EXPERIMENT_EXPOSURE_EVENT_CUTOFF in
products/experiments/backend/hogql_queries/exposure_query_logic.py; build_variant_property in
experiment_exposure_query_builder.py; isMultivariateFeatureFlagCalledEvent in
nodejs/src/ingestion/common/steps/event-processing/create-event-step.ts. -->

### Raw responses

```sql
-- Default exposure event: what the application sent, per response
SELECT
    properties.$feature_flag_response AS response,
    count() AS events,
    uniq(person_id) AS persons,
    uniq(distinct_id) AS distinct_ids,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '<resolved_exposure_event>'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= toDateTime('<window_start>', 'UTC')
  AND timestamp < toDateTime('<window_end>', 'UTC')
GROUP BY response
ORDER BY events DESC
LIMIT 50
```

```sql
-- Custom exposure event: the values of the variant property
SELECT
    properties.`$feature/<flag-key>` AS variant_value,
    count() AS events,
    uniq(person_id) AS persons,
    uniq(distinct_id) AS distinct_ids,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '<custom-exposure-event>'
  AND timestamp >= toDateTime('<window_start>', 'UTC')
  AND timestamp < toDateTime('<window_end>', 'UTC')
GROUP BY variant_value
ORDER BY events DESC
LIMIT 50
```

Read off:

- **Rows that are no variant key.**
  The experiment drops them: `false`, an empty value, a key with another spelling or case, `holdout-<id>`.
  `false` and an empty value exist only on `$feature_flag_called`: when `resolved_exposure_event` is `$experiment_exposure`, run the first query on `$feature_flag_called` to see them.
  They are not people in several variants, and no event ever carries `$multiple`.
  Whether they are a finding depends on who they are (A10 in `bias-and-skew.md`).
  When every row is one of them, walk the B series.
- **`holdout-<id>`.** People in the experiment's holdout. Expected, and outside the analysis.
- **`distinct_ids / persons` above 1** for a variant: people evaluated the flag under several linked ids (A3).
- **`last_seen` per variant.** One variant far behind the other means the application still sends the event for one arm only.
  All variants behind, on a running experiment, means the application stopped sending it.
  Both: the closing section of `empty-experiment.md`.
- **`events` far above `persons`** is normal.
  The experiment counts each person once.

### By day and library

For A2 and A9: where a gap between the arms sits, and since when.

```sql
SELECT
    toDate(timestamp) AS day,
    properties.$lib AS lib,
    properties.$feature_flag_response AS response,
    count() AS events,
    uniq(person_id) AS persons
FROM events
WHERE event = '<resolved_exposure_event>'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= toDateTime('<window_start>', 'UTC')
  AND timestamp < toDateTime('<window_end>', 'UTC')
GROUP BY day, lib, response
ORDER BY day, lib, response
LIMIT 200
```

`persons` counts everyone who sent the event on that day, returning people included.
The experiment's daily series counts each person once, on the day of the first exposure, so compare the two by their shape, not day by day.
To see whether one arm's exposures come from a page the other arm never reaches (A9), group by `properties.$pathname` in place of `lib`, on one day.

## Metric rows with `data: null`

Powers the "results won't load" complaint.

Each row in `metrics.primary.results` and `metrics.secondary.results` of `experiment-results-get` keeps its position, and a row whose query failed in this call has `data: null`.
The tool sends every metric query at once, so on an experiment with many metrics some rows can fail on load or on a timeout while the metric itself is sound.
The tool keeps no error text: any failed query gives `data: null`, so the row does not say why it failed.

**A single call with `data: null` rows is not evidence that a metric is broken.**
Tell the two apart before reporting it:

- **Read the stored results.**
  A metric with a completed result there computes.
  A metric with `status: failed` and an `error_message` there failed in the stored calculation too: inspect its definition (D11 in `numbers-vs-sql.md`).
- **Do not repeat `experiment-results-get` to see whether the rows fill in.**
  Each call runs the failed queries again.

Two cautions:

- **Don't conflate the _count_ of null rows with severity.**
  Experiments with dozens of metrics show the most failed rows in one call, because more queries compete.
- **Backend results health ≠ the user's in-app loading experience.**
  A complaint that the results page does not load, on an experiment whose stored results are complete, is a loading problem of the page.
  Do not report it as a broken metric.
  Many or very heavy metrics (a funnel with dozens of steps, an exposure filter on a property that is expensive to read) are a cause the user can change.

## Changes after launch

Powers A6, E3, E5, E7, E9, E16 and E17.

Read the changes in every diagnosis.
If the user reports a _surprising change_ (the ratio flipped, the numbers moved after an edit, the flag went to 0/100), read them first, before the stored results.

- **`experiment-activity { id: <experiment_id> }`** — the changes of the experiment, of the holdout and shared metrics attached to it now, and of its linked flag, newest first, each with the field values before and after.
  The flag's changes are left out when the caller has no access to the flag: a history without any flag entry is then no evidence that the flag did not change.
  Every lifecycle action is a change of its field: a launch and a reset change `start_date`, an end changes `end_date`, a pause and a resume change the flag's `active`, a freeze and an unfreeze change the flag's release conditions, a ship changes the flag's variants.
  Newer actions also have a named entry (`paused`, `resumed`, `exposure_frozen`, `exposure_unfrozen`, `variant_shipped`).
  Older ones do not, so the field change is the evidence and a missing named entry proves nothing.
- **`feature-flags-activity-retrieve { id: <feature_flag_id> }`** — the flag's own history, with the same diffs.
  It is the shorter read for a question about the split, the release conditions or the flag's state.

The history is long on an experiment that was running before mid-September 2026: most of its older entries are updates of the running-time estimate (`running_time_calculation`), which change nothing in the analysis.
Newer updates of the estimate leave no entry.
Page with `limit`, skip those entries, and read back to the launch before you say that nothing changed.

**The split of the run is in the history, not on the flag.**
`experiment-get` shows the flag as it is now.
After a ship that is 100/0, and after any edit it is the edited value.
The split that the exposures were assigned under is the flag's value at `start_date`, plus every change since.
After a reset, `start_date` is the relaunch: an edit before it belongs to the earlier run.

- **`advanced-activity-logs-list`** — the same log across the project, where the organization's plan includes the tool.
  It returns the field-level diffs when `fields` is omitted or includes `detail.changes`.

A8 (a change of the `distinct_id` strategy) is a change in the user's code and does _not_ show up here — diagnose it from event-side identity signals, not the activity log.

## Handing off the snapshot

If the snapshot already disproves a diagnostic, skip it; if it confirms one, lead the response with
the evidence ("the data shows X → that's diagnostic Y").
