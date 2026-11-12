# Source part queries

Read the placeholders and HogQL rules in [queries.md](queries.md) first.

## Breakdown inside a source

`part` is the setting-level item inside a source: a scanner, an evaluation, an alert, a ticket channel and priority, a severity, or a page.
Error tracking has no `part`, because its signal types are already separate rows in `source_type`.
Filter the results to the source you are reading.

```sql
SELECT
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_product'), '') AS source_product,
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_type'), '') AS source_type,
    multiIf(
        source_product = 'replay_vision', JSONExtractString(m.metadata, 'extra', 'scanner_name'),
        source_product = 'llm_analytics', JSONExtractString(m.metadata, 'extra', 'evaluation_name'),
        source_type = 'anomaly_investigation', JSONExtractString(m.metadata, 'extra', 'alert_name'),
        source_product = 'conversations', concat(JSONExtractString(m.metadata, 'extra', 'channel_source'), ' / ', JSONExtractString(m.metadata, 'extra', 'priority')),
        source_product = 'pganalyze', JSONExtractString(m.metadata, 'extra', 'severity'),
        source_product = 'google_search_console', JSONExtractString(m.metadata, 'extra', 'page'),
        ''
    ) AS part,
    sum(a.credits) AS recorded_credits,
    sumIf(a.credits, a.kind = 'ad-hoc') AS processing_credits,
    sumIf(a.credits, a.kind IN ('research', 'repo_selection')) AS research_credits,
    sumIf(a.credits, a.kind IN ('reviewer_triggered_implementation', 'scout_triggered_implementation')) AS implementation_credits
FROM (
    SELECT
        s.credits AS credits,
        s.kind AS kind,
        if(s.report_key != '', r.trigger_key, s.signal_key) AS signal_key
    FROM (
        SELECT
            credits, kind,
            ifNull(toString(report_id), '') AS report_key,
            ifNull(toString(signal_id), '') AS signal_key
        FROM system.signal_spend
        WHERE finalized_at >= {date_from} AND finalized_at < {date_to}
            AND kind != 'scout_run'
    ) AS s
    LEFT JOIN (
        SELECT toString(id) AS rid, toString(triggering_signal_id) AS trigger_key
        FROM system.inbox_reports
    ) AS r ON s.report_key = r.rid
) AS a
LEFT JOIN (
    SELECT document_id, argMax(metadata, inserted_at) AS metadata
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals' AND document_type = 'signal' AND rendering = 'plain'
    GROUP BY document_id
) AS m ON a.signal_key = m.document_id
GROUP BY source_product, source_type, part
ORDER BY recorded_credits DESC
LIMIT 300
```

Yield for the same parts:

```sql
SELECT
    b.source_product AS source_product,
    b.source_type AS source_type,
    b.part AS part,
    uniqExactIf(b.report_id, b.ts >= {date_from}) AS reports_created,
    uniqExactIf(b.report_id, r.settled = 1) AS settled_reports,
    uniqExactIf(b.report_id, r.settled = 1 AND r.status = 'resolved') AS settled_resolved,
    round(settled_resolved / greatest(settled_reports, 1), 3) AS settled_rate
FROM (
    SELECT
        document_id,
        min(timestamp) AS ts,
        argMax(JSONExtractString(metadata, 'source_product'), inserted_at) AS source_product,
        argMax(JSONExtractString(metadata, 'source_type'), inserted_at) AS source_type,
        argMax(JSONExtractString(metadata, 'report_id'), inserted_at) AS report_id,
        argMax(multiIf(
            JSONExtractString(metadata, 'source_product') = 'replay_vision', JSONExtractString(metadata, 'extra', 'scanner_name'),
            JSONExtractString(metadata, 'source_product') = 'llm_analytics', JSONExtractString(metadata, 'extra', 'evaluation_name'),
            JSONExtractString(metadata, 'source_type') = 'anomaly_investigation', JSONExtractString(metadata, 'extra', 'alert_name'),
            JSONExtractString(metadata, 'source_product') = 'conversations', concat(JSONExtractString(metadata, 'extra', 'channel_source'), ' / ', JSONExtractString(metadata, 'extra', 'priority')),
            JSONExtractString(metadata, 'source_product') = 'pganalyze', JSONExtractString(metadata, 'extra', 'severity'),
            JSONExtractString(metadata, 'source_product') = 'google_search_console', JSONExtractString(metadata, 'extra', 'page'),
            ''
        ), inserted_at) AS part
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals'
        AND document_type = 'signal'
        AND rendering = 'plain'
        AND timestamp >= {yield_from}
        AND timestamp < {date_to}
    GROUP BY document_id
) AS b
LEFT JOIN (
    SELECT
        toString(id) AS rid,
        status,
        if(first_visible_at IS NOT NULL AND first_visible_at <= now() - INTERVAL 14 DAY, 1, 0) AS settled
    FROM system.inbox_reports
) AS r ON r.rid = b.report_id
WHERE b.report_id != ''
GROUP BY source_product, source_type, part
ORDER BY reports_created DESC
LIMIT 300
```

Join the two results by source and part when you present them.
Both queries stop at 300 rows, and a project with many alerts or pages can reach that. If a result has exactly 300 rows, it is cut off: run it again for one source, with `HAVING source_product = '...'` in the spend query and `AND b.source_product = '...'` in the yield query.
A source whose parts are each small (under about $5 a month) has nothing worth narrowing. Say that, and move on.
