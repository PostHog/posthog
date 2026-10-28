# Queries

Run these with `execute-sql`.
Replace `{date_from}` and `{date_to}` with the period bounds, for example `toDateTime('2026-10-01 00:00:00')`.

## Spend by signal source

```sql
SELECT
    source_product,
    source_type,
    count() AS signals,
    uniqExactIf(report_id, report_id != '') AS reports,
    round(sum(spend) / 100, 2) AS spend_usd,
    round(sum(spend) / 100 / greatest(uniqExactIf(report_id, report_id != ''), 1), 2) AS usd_per_report,
    countIf(failed > 0) AS incomplete
FROM (
    SELECT
        document_id,
        argMax(JSONExtractString(metadata, 'source_product'), inserted_at) AS source_product,
        argMax(JSONExtractString(metadata, 'source_type'), inserted_at) AS source_type,
        argMax(JSONExtractString(metadata, 'report_id'), inserted_at) AS report_id,
        argMax(JSONExtractFloat(metadata, 'total_spend'), inserted_at) AS spend,
        argMax(JSONLength(JSONExtractRaw(metadata, 'spend_accounting_failed_stages')), inserted_at) AS failed
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals'
        AND document_type = 'signal'
        AND rendering = 'plain'
        AND timestamp >= {date_from}
        AND timestamp < {date_to}
    GROUP BY document_id
)
WHERE source_product NOT IN ('health_checks', 'engineering_analytics')
GROUP BY source_product, source_type
ORDER BY spend_usd DESC
```

A signal without a `total_spend` key has no spend yet and counts as zero.

## Signal spend by day

```sql
SELECT
    toDate(ts) AS day,
    round(sum(spend) / 100, 2) AS spend_usd,
    count() AS signals
FROM (
    SELECT
        document_id,
        min(timestamp) AS ts,
        argMax(JSONExtractString(metadata, 'source_product'), inserted_at) AS source_product,
        argMax(JSONExtractFloat(metadata, 'total_spend'), inserted_at) AS spend
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals'
        AND document_type = 'signal'
        AND rendering = 'plain'
        AND timestamp >= {date_from}
        AND timestamp < {date_to}
    GROUP BY document_id
)
WHERE source_product NOT IN ('health_checks', 'engineering_analytics')
GROUP BY day
ORDER BY day
```

Add `source_product` to the outer `SELECT` and `GROUP BY` to see which source drives a spike.

## Spend by scout

```sql
SELECT
    skill_name AS scout,
    JSONExtractString(metadata, 'skill_origin') AS origin,
    count() AS runs,
    round(sum(total_spend) / 100, 2) AS spend_usd,
    countIf(JSONLength(ifNull(emitted_report_ids, '[]')) = 0
        AND JSONLength(ifNull(edited_report_ids, '[]')) = 0) AS empty_runs,
    sum(JSONLength(ifNull(emitted_report_ids, '[]'))) AS reports_created,
    sum(JSONLength(ifNull(edited_report_ids, '[]'))) AS reports_edited
FROM system.scout_runs
WHERE created_at >= {date_from}
    AND created_at < {date_to}
GROUP BY scout, origin
ORDER BY spend_usd DESC
```

`origin` is `canonical` for scouts PostHog ships and `custom` for scouts the project wrote.
For daily scout spend, group by `toDate(created_at)` instead of the scout.

If `system.scout_runs` has no `total_spend` column, the run counts in this query still work.
Get spend from `scout-runs-list` instead.
It returns at most 100 runs per call, so page through the period one day at a time with `date_from` and `date_to`, and add up `total_spend` per `skill_name`.

## Signals created by scouts

A scout can emit signals, and those signals carry their own spend.
This query charges that spend to the scout that emitted the signals.

```sql
SELECT
    r.skill_name AS scout,
    count() AS signals,
    round(sum(s.spend) / 100, 2) AS spend_usd
FROM (
    SELECT
        document_id,
        argMax(JSONExtractString(metadata, 'source_id'), inserted_at) AS source_id,
        argMax(JSONExtractFloat(metadata, 'total_spend'), inserted_at) AS spend
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals'
        AND document_type = 'signal'
        AND rendering = 'plain'
        AND timestamp >= {date_from}
        AND timestamp < {date_to}
        AND JSONExtractString(metadata, 'source_product') = 'signals_scout'
    GROUP BY document_id
) AS s
INNER JOIN system.scout_run_emissions AS e ON e.source_id = s.source_id
INNER JOIN system.scout_runs AS r ON r.id = e.run_id
GROUP BY scout
ORDER BY spend_usd DESC
```

This spend is already part of "Spend by signal source" under `signals_scout`. Do not add it to the total twice.

## Yield

- Reports per source or scout: `inbox-reports-list` with `source_product` or `scout`, then read `count`.
- What happened to each report: join `report_id` to `system.inbox_reports` for status, `system.inbox_report_actions` for actions taken or dismissals, and `system.inbox_report_pull_requests` for pull requests and merges.
