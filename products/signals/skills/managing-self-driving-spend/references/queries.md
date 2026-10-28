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

Yield is the number of reports resolved.
A report is resolved when its status is `resolved`: someone resolved it, or its pull request merged.
Dismissed reports have the status `suppressed` and do not count.

A report needs time to resolve, so recent reports always look worse than they will.
`settled_reports` counts the reports first shown in the inbox at least 14 days ago.
Judge a source or scout on its settled reports.
When most reports in the period are not settled, say so in the report (see the report template).

HogQL does not allow a function call in a join condition, so each subquery converts the report id to a string first.

### Yield by signal source

```sql
SELECT
    b.source_product AS source_product,
    b.source_type AS source_type,
    count() AS reports,
    countIf(r.status = 'resolved') AS resolved,
    countIf(r.status = 'suppressed') AS dismissed,
    countIf(r.settled = 1) AS settled_reports,
    countIf(r.settled = 1 AND r.status = 'resolved') AS settled_resolved,
    round(sum(b.spend) / 100, 2) AS spend_usd,
    round(sum(b.spend) / 100 / greatest(countIf(r.status = 'resolved'), 1), 2) AS usd_per_resolved
FROM (
    SELECT source_product, source_type, report_id, sum(spend) AS spend
    FROM (
        SELECT
            document_id,
            argMax(JSONExtractString(metadata, 'source_product'), inserted_at) AS source_product,
            argMax(JSONExtractString(metadata, 'source_type'), inserted_at) AS source_type,
            argMax(JSONExtractString(metadata, 'report_id'), inserted_at) AS report_id,
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
        AND report_id != ''
    GROUP BY source_product, source_type, report_id
) AS b
LEFT JOIN (
    SELECT
        toString(id) AS rid,
        status,
        if(first_visible_at IS NOT NULL AND first_visible_at <= now() - INTERVAL 14 DAY, 1, 0) AS settled
    FROM system.inbox_reports
) AS r ON r.rid = b.report_id
GROUP BY source_product, source_type
ORDER BY spend_usd DESC
```

A report with signals from several sources counts once under each source.
Its spend splits correctly, because each signal carries its own spend.

### Yield by scout

```sql
SELECT
    e.scout AS scout,
    count() AS reports_created,
    countIf(r.status = 'resolved') AS resolved,
    countIf(r.status = 'suppressed') AS dismissed,
    countIf(r.settled = 1) AS settled_reports,
    countIf(r.settled = 1 AND r.status = 'resolved') AS settled_resolved
FROM (
    SELECT DISTINCT
        skill_name AS scout,
        arrayJoin(JSONExtract(ifNull(emitted_report_ids, '[]'), 'Array(String)')) AS report_id
    FROM system.scout_runs
    WHERE created_at >= {date_from}
        AND created_at < {date_to}
) AS e
LEFT JOIN (
    SELECT
        toString(id) AS rid,
        status,
        if(first_visible_at IS NOT NULL AND first_visible_at <= now() - INTERVAL 14 DAY, 1, 0) AS settled
    FROM system.inbox_reports
) AS r ON r.rid = e.report_id
GROUP BY scout
ORDER BY reports_created DESC
```

This counts only the reports a scout created.
A scout that mostly edits existing reports shows little yield here, so check `reports_edited` in "Spend by scout" before you judge it.
A scout that writes digests or sends findings to Slack may resolve nothing and still be useful. Ask the user before you recommend pausing one.
