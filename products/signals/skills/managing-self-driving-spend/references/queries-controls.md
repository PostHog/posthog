# Control queries

Read the placeholders and HogQL rules in [queries.md](queries.md) first.

## Reports shown per day

The daily report limit counts days in the project timezone. Read it from `posthog:project-get`.

```sql
SELECT
    toDate(toTimeZone(first_visible_at, {project_timezone})) AS day,
    count() AS reports_shown
FROM system.inbox_reports
WHERE first_visible_at >= now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
```

## Pull requests linked and merged

Use these queries to judge merge rate, and use the ledger to judge cost.
They count pull requests on reports created since `{yield_from}` and age them from the report, so do not present the counts as pull requests opened in a period.
Scout reports appear under the `signals_scout` source, and the by-scout query splits them by scout.

A pull request on a report does not always have an implementation receipt. A person can start the fix, which is metered as PostHog AI, and some links are imports of older work.
So a missing receipt does not show missing spend, and pull request counts do not show what fixes cost.

By source:

```sql
SELECT
    JSONExtractString(ifNull(m.metadata, '{}'), 'source_product') AS source_product,
    JSONExtractString(ifNull(m.metadata, '{}'), 'source_type') AS source_type,
    uniqExact(x.prid) AS prs_linked,
    uniqExactIf(x.prid, ifNull(x.merged, 0) = 1) AS prs_merged,
    uniqExactIf(x.prid, x.report_created_at <= now() - INTERVAL 14 DAY) AS settled_prs,
    uniqExactIf(x.prid, x.report_created_at <= now() - INTERVAL 14 DAY AND ifNull(x.merged, 0) = 1) AS settled_merged
FROM (
    SELECT a.prid AS prid, r.report_created_at AS report_created_at, p.merged AS merged, r.trigger_key AS trigger_key
    FROM (
        SELECT toString(pull_request_id) AS prid, toString(report_id) AS rid
        FROM system.inbox_report_artefacts
        WHERE type = 'pull_request'
    ) AS a
    INNER JOIN (
        SELECT toString(id) AS report_key, toString(triggering_signal_id) AS trigger_key, created_at AS report_created_at
        FROM system.inbox_reports
        WHERE created_at >= {yield_from}
    ) AS r ON a.rid = r.report_key
    LEFT JOIN (
        SELECT toString(id) AS pid, if(state = 'merged', 1, 0) AS merged
        FROM system.inbox_report_pull_requests
    ) AS p ON a.prid = p.pid
) AS x
LEFT JOIN (
    SELECT document_id, argMax(metadata, inserted_at) AS metadata
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals' AND document_type = 'signal' AND rendering = 'plain'
    GROUP BY document_id
) AS m ON x.trigger_key = m.document_id
GROUP BY source_product, source_type
ORDER BY prs_linked DESC
```

Reports created before mid-October 2026 have no triggering signal, so their pull requests land in a row with an empty source.
That row is not a source. Leave it out when you compare sources.

By the scout that authored the report:

```sql
SELECT
    e.scout AS scout,
    uniqExact(a.prid) AS prs_linked,
    uniqExactIf(a.prid, ifNull(p.merged, 0) = 1) AS prs_merged,
    uniqExactIf(a.prid, r.report_created_at <= now() - INTERVAL 14 DAY) AS settled_prs,
    uniqExactIf(a.prid, r.report_created_at <= now() - INTERVAL 14 DAY AND ifNull(p.merged, 0) = 1) AS settled_merged
FROM (
    SELECT toString(pull_request_id) AS prid, toString(report_id) AS rid
    FROM system.inbox_report_artefacts
    WHERE type = 'pull_request'
) AS a
INNER JOIN (
    SELECT DISTINCT
        skill_name AS scout,
        arrayJoin(JSONExtract(ifNull(emitted_report_ids, '[]'), 'Array(String)')) AS report_id
    FROM system.scout_runs
    WHERE created_at >= {yield_from}
) AS e ON a.rid = e.report_id
INNER JOIN (
    SELECT toString(id) AS report_key, created_at AS report_created_at
    FROM system.inbox_reports
    WHERE created_at >= {yield_from}
) AS r ON a.rid = r.report_key
LEFT JOIN (
    SELECT toString(id) AS pid, if(state = 'merged', 1, 0) AS merged
    FROM system.inbox_report_pull_requests
) AS p ON a.prid = p.pid
GROUP BY scout
ORDER BY prs_linked DESC
LIMIT 50
```
