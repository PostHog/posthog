# Web traffic channels (direct, organic search, etc)

Channels are the different sources that bring traffic to your website, e.g. Paid Search, Organic Social, Direct, etc.

```sql
SELECT
    nullIf(nullIf(multiIf(match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_campaign, ''), 'null')), ''), 'null')), 'cross-network'), 'Cross Network', or(in(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null')), tuple('cpc', 'cpm', 'cpv', 'cpa', 'ppc', 'retargeting')), startsWith(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null')), 'paid'), has_gclid, notEquals(nullIf(nullIf(if(has_gad_source_paid_search, '1', NULL), ''), 'null'), NULL)), coalesce(lookupPaidSourceType(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_source, ''), 'null')), ''), 'null'))), if(match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_campaign, ''), 'null')), ''), 'null')), '^(.*(([^a-df-z]|^)shop|shopping).*)$'), 'Paid Shopping', NULL), lookupPaidMediumType(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null'))), lookupPaidSourceType(nullIf(nullIf(referring_domain, ''), 'null')), multiIf(equals(nullIf(nullIf(if(has_gad_source_paid_search, '1', NULL), ''), 'null'), '1'), 'Paid Search', match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_campaign, ''), 'null')), ''), 'null')), '^(.*video.*)$'), 'Paid Video', has_fbclid, 'Paid Social', 'Paid Unknown')), and(equals(nullIf(nullIf(referring_domain, ''), 'null'), '$direct'), equals(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null')), NULL), or(equals(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_source, ''), 'null')), ''), 'null')), NULL), in(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_source, ''), 'null')), ''), 'null')), tuple('(direct)', 'direct', '$direct'))), not(has_fbclid)), 'Direct', coalesce(lookupOrganicSourceType(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_source, ''), 'null')), ''), 'null'))), if(match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_campaign, ''), 'null')), ''), 'null')), '^(.*(([^a-df-z]|^)shop|shopping).*)$'), 'Organic Shopping', NULL), lookupOrganicMediumType(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null'))), lookupOrganicSourceType(nullIf(nullIf(referring_domain, ''), 'null')), multiIf(match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_campaign, ''), 'null')), ''), 'null')), '^(.*video.*)$'), 'Organic Video', match(lower(nullIf(nullIf(lower(nullIf(nullIf(utm_medium, ''), 'null')), ''), 'null')), 'push$'), 'Push', has_fbclid, 'Organic Social', equals(nullIf(nullIf(referring_domain, ''), 'null'), '$direct'), 'Direct', notEquals(nullIf(nullIf(referring_domain, ''), 'null'), NULL), 'Referral', 'Unknown'))), ''), 'null') AS `context.columns.breakdown_value`,
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
OFFSET 0",
```
