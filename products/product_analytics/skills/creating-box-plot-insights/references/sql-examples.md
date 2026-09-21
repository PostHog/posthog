# SQL box plot examples

Run each query with `posthog:execute-sql` before using it in an insight.

## Deterministic sample data

Use this query to test the full SQL box plot flow without relying on project event properties:

```sql
SELECT
    bucket AS x,
    series,
    min(value) AS min,
    quantile(0.25)(value) AS p25,
    quantile(0.5)(value) AS median,
    avg(value) AS mean,
    quantile(0.75)(value) AS p75,
    max(value) AS max
FROM (
    SELECT
        concat('Week ', toString(modulo(number, 4) + 1)) AS bucket,
        if(modulo(intDiv(number, 4), 2) = 0, 'Free', 'Paid') AS series,
        toFloat(
            modulo(number * 37, 100)
            + if(modulo(intDiv(number, 4), 2) = 0, 0, 20)
        ) AS value
    FROM numbers(1000)
)
GROUP BY bucket, series
ORDER BY bucket, series
```

Map `xAxisColumn` to `x` and `seriesColumn` to `series`.

## Event property over time

Replace the event, property, and series expression with values from the user's project:

```sql
SELECT
    toStartOfWeek(timestamp) AS x,
    properties.plan AS series,
    min(toFloat(properties.latency_ms)) AS min,
    quantile(0.25)(toFloat(properties.latency_ms)) AS p25,
    quantile(0.5)(toFloat(properties.latency_ms)) AS median,
    avg(toFloat(properties.latency_ms)) AS mean,
    quantile(0.75)(toFloat(properties.latency_ms)) AS p75,
    max(toFloat(properties.latency_ms)) AS max
FROM events
WHERE
    event = 'request completed'
    AND timestamp >= now() - INTERVAL 8 WEEK
    AND properties.latency_ms IS NOT NULL
GROUP BY x, series
ORDER BY x, series
```

Use `toFloatOrNull` instead of `toFloat` when the property can contain non-numeric strings, then filter null values in an inner query before aggregating.

## One overall distribution

Return one row and set both grouping fields to `null`:

```sql
SELECT
    min(toFloat(properties.latency_ms)) AS min,
    quantile(0.25)(toFloat(properties.latency_ms)) AS p25,
    quantile(0.5)(toFloat(properties.latency_ms)) AS median,
    avg(toFloat(properties.latency_ms)) AS mean,
    quantile(0.75)(toFloat(properties.latency_ms)) AS p75,
    max(toFloat(properties.latency_ms)) AS max
FROM events
WHERE
    event = 'request completed'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND properties.latency_ms IS NOT NULL
```

Use:

```json
{
  "xAxisColumn": null,
  "seriesColumn": null
}
```

## One box per series, without an X-axis

Return one row per series and set only `xAxisColumn` to `null`:

```sql
SELECT
    properties.plan AS series,
    min(toFloat(properties.latency_ms)) AS min,
    quantile(0.25)(toFloat(properties.latency_ms)) AS p25,
    quantile(0.5)(toFloat(properties.latency_ms)) AS median,
    avg(toFloat(properties.latency_ms)) AS mean,
    quantile(0.75)(toFloat(properties.latency_ms)) AS p75,
    max(toFloat(properties.latency_ms)) AS max
FROM events
WHERE
    event = 'request completed'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND properties.latency_ms IS NOT NULL
GROUP BY series
ORDER BY series
```
