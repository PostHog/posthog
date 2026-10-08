# Funnel metric events precomputation

## Problem

An experiment funnel query has three CTEs: `exposures`, `metric_events`, and `entity_metrics`. The `exposures` CTE is already precomputed (see `LAZY_COMPUTATION.md`). The `metric_events` CTE still scans the events table on every query:

```sql
metric_events AS (
    SELECT
        person_id AS entity_id,
        properties.$feature_flag_response AS variant,
        timestamp,
        uuid,
        properties.$session_id AS session_id,
        step_0,  -- 1 if this is an exposure event, else 0
        step_1,  -- 1 if this matches funnel step 1, else 0
        step_2   -- 1 if this matches funnel step 2, else 0
    FROM events
    WHERE (exposure_predicate OR funnel_steps_filter)
)
```

This scans every event that matches the exposure criteria OR any funnel step (e.g. `pageview`, `purchase`). For high-traffic experiments, this is millions of rows — and it runs on every query.

## Solution

Scan the events table once, store matching events in `experiment_metric_events_preaggregated`, and read from there on subsequent queries.

## What gets stored

One row per matching event. The step indicators are packed into an `Array(UInt8)`:

```text
┌──────────┬──────────┬───────────┬─────────────────────┬───────────┬────────────┬───────────┐
│ team_id  │ job_id   │ entity_id │ timestamp           │ event_uuid│ session_id │ steps     │
├──────────┼──────────┼───────────┼─────────────────────┼───────────┼────────────┼───────────┤
│ 123      │ job-A    │ user-1    │ 2026-01-02 10:00:00 │ evt-111   │ sess-1     │ [1, 0, 0] │  ← exposure
│ 123      │ job-A    │ user-1    │ 2026-01-02 11:00:00 │ evt-222   │ sess-1     │ [0, 1, 0] │  ← pageview
│ 123      │ job-A    │ user-1    │ 2026-01-02 12:00:00 │ evt-333   │ sess-1     │ [0, 0, 1] │  ← purchase
│ 123      │ job-A    │ user-2    │ 2026-01-02 14:00:00 │ evt-444   │ sess-2     │ [1, 0, 0] │  ← exposure
│ 123      │ job-A    │ user-2    │ 2026-01-02 15:00:00 │ evt-555   │ sess-2     │ [0, 1, 0] │  ← pageview
│ ...      │          │           │                     │           │            │           │
└──────────┴──────────┴───────────┴─────────────────────┴───────────┴────────────┴───────────┘
```

`steps = [1, 0, 0]` means: this event matches step_0 (exposure) but not step_1 or step_2.

## Data flow

### Without precomputation

```text
┌────────────────────────────────┐
│         events table           │
│       (millions of rows)       │
└───────┬───────────────┬────────┘
        │               │
        │ scan for      │ scan for pageview,
        │ exposures     │ purchase, etc.
        │               │
        ▼               ▼
  exposures CTE   metric_events CTE ◄── THIS IS THE EXPENSIVE PART
        │               │
        └───────┬───────┘
                │ LEFT JOIN
                ▼
        entity_metrics CTE
        (aggregate_funnel_array UDF)
                │
                ▼
          Final result
```

### With precomputation

```text
  FIRST QUERY (precomputes):

  events table ──scan──▶ experiment_metric_events_preaggregated
                         (stores matching events with step indicators)


  SUBSEQUENT QUERIES (reads from cache):

  ┌─────────────────────────┐    ┌───────────────────────────────────┐
  │ experiment_exposures    │    │ experiment_metric_events          │
  │ _preaggregated          │    │ _preaggregated                   │
  │ (already cached)        │    │ (newly cached)                   │
  └──────────┬──────────────┘    └────────────────┬──────────────────┘
             │                                    │
             ▼                                    ▼
       exposures CTE                      metric_events CTE
             │                                    │
             └──────────┬─────────────────────────┘
                        │ LEFT JOIN
                        ▼
                entity_metrics CTE        ← same UDF, same logic
                        │
                        ▼
                  Final result            ← identical output
```

## How it works

### Write path: `get_funnel_metric_events_query_for_precomputation()`

The builder produces a query template with `{time_window_min}` and `{time_window_max}` placeholders:

```sql
SELECT
    person_id AS entity_id,
    timestamp AS timestamp,
    uuid AS event_uuid,
    `$session_id` AS session_id,
    [toUInt8(if(exposure_pred, 1, 0)),
     toUInt8(if(step_1_pred, 1, 0)),
     toUInt8(if(step_2_pred, 1, 0))] AS steps
FROM events
WHERE timestamp >= {time_window_min}
    AND timestamp < {time_window_max}
    AND (exposure_predicate OR funnel_steps_filter)
```

The lazy computation system (`ensure_precomputed()`) splits the experiment date range into daily windows, fills in the time placeholders, and wraps the SELECT in an INSERT:

```sql
INSERT INTO experiment_metric_events_preaggregated
    (team_id, job_id, entity_id, timestamp, event_uuid, session_id, steps, expires_at)
SELECT
    123 AS team_id,
    'job-uuid' AS job_id,
    ... -- the SELECT from above
```

Each daily window becomes a separate job. Already-computed windows are skipped.

### Read path: `build_funnel_query_legacy()`

When the funnel builder gets metric-events job ids, the metric_events CTE of the three-CTE path reads from the precomputed table instead of scanning events.
The single-scan path ignores them and scans events. The funnel takes that path when its exposure select does not read precomputed exposures (`ExposureQueryBuilder.reads_precomputed()`).

```sql
metric_events AS (
    SELECT
        toUUID(t.entity_id) AS entity_id,
        t.timestamp AS timestamp,
        t.event_uuid AS uuid,
        t.session_id AS session_id,
        arrayElement(t.steps, 1) AS step_0,
        arrayElement(t.steps, 2) AS step_1,
        arrayElement(t.steps, 3) AS step_2
    FROM experiment_metric_events_preaggregated AS t
    WHERE t.job_id IN ('job-A', 'job-B')
        AND t.team_id = 123
)
```

`arrayElement(t.steps, N)` extracts individual step indicators from the packed array. The rest of the query (entity_metrics CTE, `aggregate_funnel_array` UDF, final aggregation) is unchanged.

### Wiring: `_get_experiment_query()`

The runner orchestrates both precomputations, then hands the job ids to `build_query()`:

```python
if should_precompute and not self.is_data_warehouse_query and self.group_type_index is None:
    result = self._ensure_exposures_precomputed(builder)
    if result.ready:
        exposure_job_ids = [str(job_id) for job_id in result.job_ids]

    if self._metric_events_precompute_applicable():
        metric_result = self._ensure_metric_events_precomputed(builder)
        if metric_result.ready:
            metric_events_job_ids = [str(job_id) for job_id in metric_result.job_ids]

return builder.build_query(
    precomputation_context=ExperimentPrecomputationContext(
        exposure_job_ids=exposure_job_ids,
        metric_events_job_ids=metric_events_job_ids,
    )
)
```

`build_query()` does not store the job ids on the builder.
It builds one exposure builder with the exposure job ids and passes it, with the metric-events job ids, to the metric builder of that build.

Both use the same lazy computation system (daily windows, job management, TTL).

## Conversion window

Funnel steps can occur after the experiment end date (within the conversion window). Example: experiment ends Jan 15, conversion window is 7 days, a purchase on Jan 20 still counts.

The runner extends `time_range_end` by the conversion window when precomputing metric events:

```python
date_to = experiment.end_date + timedelta(seconds=conversion_window_seconds)
```

The exposure precomputation does NOT need this extension — exposures only occur within the experiment date range.

## Key differences from exposure precomputation

|                            | Exposures                              | Metric events                              |
| -------------------------- | -------------------------------------- | ------------------------------------------ |
| **Granularity**            | 1 row per user per job                 | 1 row per event per job                    |
| **Re-aggregation on read** | Yes — `argMin`/`min`/`max` across jobs | No — events are unique per daily window    |
| **Table**                  | `experiment_exposures_preaggregated`   | `experiment_metric_events_preaggregated`   |
| **Time range**             | Experiment start → end                 | Experiment start → end + conversion window |
| **Stores variant**         | Yes                                    | No — variant comes from exposures CTE      |

## Scope

Implemented for **ordered funnels**, **count/sum/avg/min/max mean metrics** (per-event value stored in `numeric_value`, deduplicated on read by event identity since replayed build rows would double sums and skew averages; the aggregation itself runs at read time, so all five math types store identical rows), **dau/unique_session mean metrics** (the read counts distinct IDs from `entity_id`/`session_id`, which every mean build stores; `numeric_value` holds the same constant a count metric stores, so a count metric and an ID-math metric on the same source share build jobs), and **retention metrics**. Unordered funnels, unique-group and HogQL math, and ratio metrics are not precomputed; breakdowns, CUPED, and data warehouse sources always fall back to a direct scan.

Retention stores one row per event matching the start or completion predicate, with two flags in `steps` (`steps[1]` = matched start_event, `steps[2]` = matched completion_event; one event can match both). The read path swaps the two raw-events CTE sources for flag-filtered reads of the precomputed table; start anchoring (FIRST_SEEN/LAST_SEEN), the per-user retention window, the maturity gate, and the same-event exclusion all stay read-time, so they behave identically on both paths. The scan extension past the experiment end is `conversion_window + retention_window_end` rather than the conversion window alone, capped at 90 days (`METRIC_EVENTS_MAX_WINDOW_EXTENSION_SECONDS`); oversized windows fall back to a direct scan.

## Key files

| File                                        | Purpose                                                                                                                |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `experiment_funnel_query_builder.py`        | `get_funnel_metric_events_query_for_precomputation()` (write), precomputed CTE in `build_funnel_query_legacy()` (read) |
| `experiment_query_runner.py`                | `_ensure_metric_events_precomputed()`, wiring in `_get_experiment_query()`                                             |
| `lazy_computation_executor.py`              | Core lazy computation: `ensure_precomputed()`, job management                                                          |
| `experiment_metric_events_sql.py`           | ClickHouse table definition                                                                                            |
| `experiment_metric_events_preaggregated.py` | HogQL schema for the table                                                                                             |
