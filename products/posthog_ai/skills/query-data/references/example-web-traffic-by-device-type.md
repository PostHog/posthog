# Web traffic views by device type

```sql
SELECT
    nullIf(nullIf(device_type, ''), 'null') AS `context.columns.breakdown_value`,
    tuple(uniqMergeIf(persons_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), uniqMergeIf(persons_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.visitors`,
    tuple(sumMergeIf(pageviews_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), sumMergeIf(pageviews_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.views`,
    divide(`context.columns.visitors`.1, sum(`context.columns.visitors`.1) OVER ()) AS `context.columns.ui_fill_fraction`
FROM
    web_pre_aggregated_stats
WHERE
    and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-29 07:59:59.999999')))
GROUP BY
    `context.columns.breakdown_value`
ORDER BY
    `context.columns.visitors` DESC
LIMIT 11
OFFSET 0
```
