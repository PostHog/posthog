# Comparing flagged and unflagged traffic

These are starting points for the gate metric of a rollout.
The event `report_generated`, the property `duration_ms` and the flag `faster-report-cache` are invented, so confirm the real names with `posthog:read-data-schema` first.

The examples read `$feature/faster-report-cache`.
If the events carry the flag state in another property, such as one the team's own code sets, use that one instead.

Keep each query an aggregate.
Do not sum rows on your side from a per-group listing, because the default row limit can cut the list short.

## Flag state coverage

Run this first.
If `no_flag_state` is a large share, the flagged and unflagged comparison is not valid, because the events with no state could belong to either side.

```sql
SELECT
    multiIf(
        properties['$feature/faster-report-cache'] IS NULL, 'no_flag_state',
        properties['$feature/faster-report-cache'] = 'false', 'unflagged',
        'flagged'
    ) AS flag_state,
    count() AS events,
    count(DISTINCT $group_0) AS organizations
FROM events
WHERE event = 'report_generated'
    AND timestamp > now() - INTERVAL 1 DAY
GROUP BY flag_state
```

`$group_0` is the group type at index 0.
Read the project's mapping from `system.group_type_mappings`, and use `person_id` for a flag that buckets people.

## Load concentration

Use this before you pick steps, to see how far a percentage of groups is from a percentage of load.

```sql
WITH per_org AS (
    SELECT $group_0 AS organization, count() AS events
    FROM events
    WHERE event = 'report_generated'
        AND timestamp > now() - INTERVAL 7 DAY
        AND $group_0 != ''
    GROUP BY organization
),
ranked AS (
    SELECT events, row_number() OVER (ORDER BY events DESC) AS position
    FROM per_org
)
SELECT
    count() AS organizations,
    sum(events) AS total_events,
    round(sumIf(events, position <= 10) / sum(events), 3) AS top_10_share,
    round(sumIf(events, position <= 100) / sum(events), 3) AS top_100_share
FROM ranked
```

## Flagged and unflagged in the same window

Set the start of the window to the time of the last widening, plus time for SDKs to pick up the change.
Compare the traffic columns against the gate's minimum before you read the other columns.

```sql
SELECT
    if(properties['$feature/faster-report-cache'] = 'false', 'unflagged', 'flagged') AS flag_state,
    count() AS events,
    count(DISTINCT $group_0) AS organizations,
    countIf(properties.status = 'error') / count() AS error_rate,
    quantile(0.95)(toFloat(properties.duration_ms)) AS p95_duration_ms
FROM events
WHERE event = 'report_generated'
    AND timestamp >= '2026-03-02 09:00:00'
    AND properties['$feature/faster-report-cache'] IS NOT NULL
GROUP BY flag_state
```

## Before and after for the same units

Take the units that are flagged now, and compare them with their own traffic exactly one week earlier, so both windows cover the same weekdays and hours.

```sql
WITH flagged_orgs AS (
    SELECT DISTINCT $group_0 AS organization
    FROM events
    WHERE event = 'report_generated'
        AND timestamp >= '2026-03-02 09:00:00'
        AND timestamp < '2026-03-04 09:00:00'
        AND properties['$feature/faster-report-cache'] = 'true'
)
SELECT
    if(timestamp >= '2026-03-02 09:00:00', 'after', 'before') AS period,
    count() AS events,
    count(DISTINCT $group_0) AS organizations,
    countIf(properties.status = 'error') / count() AS error_rate,
    quantile(0.95)(toFloat(properties.duration_ms)) AS p95_duration_ms
FROM events
WHERE event = 'report_generated'
    AND $group_0 IN (SELECT organization FROM flagged_orgs)
    AND (
        (timestamp >= '2026-03-02 09:00:00' AND timestamp < '2026-03-04 09:00:00')
        OR (timestamp >= '2026-02-23 09:00:00' AND timestamp < '2026-02-25 09:00:00')
    )
GROUP BY period
```

A multivariate flag serves variant keys rather than `true`, so match the variants you are rolling out.

## Reading the results

- HogQL parses a timestamp string in the project timezone, so read the timezone with `posthog:project-get` before you write one.
- A small flagged group is noisy. A gate that fails or passes because of one large organization deserves a look at that organization before anyone acts on it.
- A difference between the groups that was already there before the rollout is not caused by the flag. Check the before and after numbers when the same-window numbers look bad.
