---
name: analyzing-funnel-correlation
description: >
  Find the events and person properties that correlate with funnel conversion or drop-off.
  Use when the user asks why people convert or drop off in a funnel, what converters do
  differently, which events or properties predict success or failure, or asks for
  "correlation analysis" on a funnel. Computes odds ratios with HogQL, because PostHog has
  no built-in funnel correlation view.
---

# Analyzing funnel correlation

Correlation compares two groups of people who entered a funnel:
people who completed the last step (success) and people who did not (failure).
For each candidate event or property value, build a contingency table and compute the odds ratio.
An odds ratio above 1 means the signal goes with conversion. Below 1 means it goes with drop-off.
The further the ratio is from 1, the stronger the correlation.

Correlation is not causation. Tell the user that, and suggest an experiment to test a strong signal.

## Workflow

1. Get the funnel definition: the step events, the date range, and the conversion window.
   If the user names a saved insight, read it with `insight-get`.
   Confirm the step events with `read-data-schema`.
2. Run the funnel with `query-funnel` and note the total entrants and converters.
   The SQL below must give totals in the same range. If not, fix the step filters first.
3. Run the event correlation query below with `execute-sql`.
4. If the user asks about person attributes, run the property variant.
5. Report the top success signals and the top failure signals with their counts.
   To show who is behind a signal, use `query-funnel-actors` or filter the funnel by that event or property.

## Event correlation

Replace the step events, the date range, the conversion window (seconds in `windowFunnel`, days in the `INTERVAL`), and the step count.
Add more `event = '...'` conditions to `windowFunnel` for more steps, and set `steps = N` to the last step.

```sql
WITH
    funnel_actors AS (
        SELECT
            person_id AS actor_id,
            windowFunnel(1209600)(toDateTime(timestamp), event = 'step one', event = 'step two') AS steps,
            arraySort(groupArrayIf((toUnixTimestamp(timestamp), event = 'step two'), event IN ('step one', 'step two'))) AS step_events,
            arrayReverseFill(t -> t > 0, arrayMap(x -> if(x.2, x.1, 0), step_events)) AS next_final,
            arrayFirstIndex((x, t) -> NOT x.2 AND t > 0 AND t <= x.1 + 1209600, step_events, next_final) AS attempt,
            toDateTime(if(attempt > 0, step_events[attempt].1, arrayFirst(x -> NOT x.2, step_events).1)) AS first_timestamp,
            toDateTime(next_final[greatest(attempt, 1)]) AS final_timestamp
        FROM events
        WHERE event IN ('step one', 'step two')
            AND timestamp >= now() - INTERVAL 30 DAY
        GROUP BY actor_id
        HAVING steps >= 1
    ),
    totals AS (
        SELECT countIf(steps = 2) AS success_total, countIf(steps < 2) AS failure_total
        FROM funnel_actors
    ),
    per_event AS (
        SELECT
            e.event AS name,
            countDistinctIf(a.actor_id, a.steps = 2) AS success_count,
            countDistinctIf(a.actor_id, a.steps < 2) AS failure_count
        FROM events AS e
        JOIN funnel_actors AS a ON e.person_id = a.actor_id
        WHERE e.timestamp >= now() - INTERVAL 30 DAY
            AND e.timestamp > a.first_timestamp
            AND e.timestamp < if(a.steps = 2, a.final_timestamp, a.first_timestamp + INTERVAL 14 DAY)
            AND e.event NOT IN ('step one', 'step two')
        GROUP BY name
    )
SELECT
    name,
    success_count,
    failure_count,
    success_total,
    failure_total,
    ((success_count + 1) * (failure_total - failure_count + 1))
        / ((success_total - success_count + 1) * (failure_count + 1)) AS odds_ratio
FROM per_event
CROSS JOIN totals
WHERE success_count + failure_count >= least(25, 0.02 * (success_total + failure_total))
ORDER BY abs(log(odds_ratio)) DESC
LIMIT 20
```

The query only counts events between funnel entry and conversion.
`step_events` holds the first-step and last-step events in time order. `next_final` gives the next last-step time for each of them in one pass.
For people who converted, `attempt` picks the first entry that has a last step inside the window, so both timestamps come from the same attempt.
For more steps, keep only the first and last step events in `groupArrayIf`. The attempt then ignores the middle steps, so the interval can start at an earlier entry than the one that converted.
For people who did not convert, it counts events from their first entry until the conversion window closes.
The timestamps use whole seconds because `windowFunnel` compares whole seconds. Keep them the same, or some converters get no matched attempt.
It excludes the funnel step events, because they correlate with conversion by definition.

## Property correlation

To compare person property values, group the actors by the property and skip the events join.

```sql
WITH
    funnel_actors AS (
        SELECT
            person_id AS actor_id,
            windowFunnel(1209600)(toDateTime(timestamp), event = 'step one', event = 'step two') AS steps,
            any(person.properties.$browser) AS value
        FROM events
        WHERE event IN ('step one', 'step two')
            AND timestamp >= now() - INTERVAL 30 DAY
        GROUP BY actor_id
        HAVING steps >= 1
    ),
    totals AS (
        SELECT countIf(steps = 2) AS success_total, countIf(steps < 2) AS failure_total
        FROM funnel_actors
    ),
    per_value AS (
        SELECT
            toString(value) AS name,
            countIf(steps = 2) AS success_count,
            countIf(steps < 2) AS failure_count
        FROM funnel_actors
        GROUP BY name
    )
SELECT
    name,
    success_count,
    failure_count,
    ((success_count + 1) * (failure_total - failure_count + 1))
        / ((success_total - success_count + 1) * (failure_count + 1)) AS odds_ratio
FROM per_value
CROSS JOIN totals
WHERE success_count + failure_count >= least(25, 0.02 * (success_total + failure_total))
ORDER BY abs(log(odds_ratio)) DESC
LIMIT 20
```

To look at the properties of one event instead, filter `per_event` to that event and group by `e.properties.<name>`.

## Read the results with care

- The `+ 1` in each cell is a prior. It prevents division by zero and damps signals from small counts.
- The `WHERE` filter drops signals seen by fewer than 25 people or 2% of entrants. Small groups give unstable ratios.
- If one group is more than 10 times bigger than the other, the ratios are less reliable. Tell the user.
- If `success_total` or `failure_total` is 0, there is nothing to compare.
- Noise events that everybody sends, such as `$pageview`, `$pageleave`, or `$feature_flag_called`, can fill the list. Exclude them when they hide the useful signals.
- For group-based funnels, replace `person_id` with `$group_N` and the person properties with group properties. Also add `AND $group_N != ''` to the funnel step `WHERE` clause. Events without that group have an empty key, and without the filter they become one fake actor that can convert.
