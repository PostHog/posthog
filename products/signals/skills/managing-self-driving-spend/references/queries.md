# Queries

Use `posthog:inbox-usage-get` for the monthly overview; run these drilldowns with `posthog:execute-sql` in its returned `project_id`.
Read the `querying-posthog-data` skill's Self-driving usage reference for schema and access details.
Replace `{date_from}` and `{date_to}` with inclusive/exclusive UTC bounds, for example `toDateTime('2026-10-01 00:00:00', 'UTC')` and `toDateTime('2026-11-01 00:00:00', 'UTC')`.
History starts October 1, 2026. Multiply credits by the monthly tool's `pricing.usd_per_credit`; do not assume credits are cents.

## Spend by day

```sql
SELECT
    toDate(finalized_at, 'UTC') AS day,
    kind,
    sum(credits) AS recorded_credits,
    sumIf(credits, billing_exempt) AS exempt_credits,
    countIf(accounting_failed) AS incomplete_records
FROM system.signal_spend
WHERE finalized_at >= {date_from} AND finalized_at < {date_to}
GROUP BY day, kind
ORDER BY day, kind
```

This includes signal processing, research, repository selection, scout execution, and implementation exactly once.
For individual work, select `id`, `signal_id`, `scout_run_id`, `report_id`, `kind`, `credits`, and `billing_exempt` with the same bounds.
For unsettled work created in the period, use `finalized_at IS NULL AND created_at >= {date_from} AND created_at < {date_to}` instead. Keep its credits separate; `accounting_failed` can describe running work.

## Spend by signal source

This reproduces source attribution, including implementation via the report's current triggering signal.
Keep the left joins and null-source group so missing metadata or deleted reports do not remove spend.
Do not filter signal metadata by arrival date: older signals can incur costs this month.

```sql
WITH spend AS (
    SELECT *, toString(report_id) AS report_key
    FROM system.signal_spend
    WHERE finalized_at >= {date_from} AND finalized_at < {date_to}
        AND kind != 'scout_run'
), attributed AS (
    SELECT
        s.credits, s.billing_exempt, s.kind,
        toString(if(s.report_id IS NOT NULL, r.triggering_signal_id, s.signal_id)) AS signal_key
    FROM spend AS s
    LEFT JOIN system.inbox_reports AS r ON s.report_key = r.id
), signals AS (
    SELECT document_id, argMax(metadata, inserted_at) AS metadata
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
        AND product = 'signals' AND document_type = 'signal' AND rendering = 'plain'
    GROUP BY document_id
)
SELECT
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_product'), '') AS source_product,
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_type'), '') AS source_type,
    sum(a.credits) AS recorded_credits,
    sumIf(a.credits, a.billing_exempt) AS exempt_credits,
    sumIf(a.credits, a.kind = 'ad-hoc') AS processing_credits,
    sumIf(a.credits, a.kind IN ('research', 'repo_selection')) AS research_credits,
    sumIf(a.credits, a.kind IN ('reviewer_triggered_implementation', 'scout_triggered_implementation')) AS implementation_credits
FROM attributed AS a
LEFT JOIN signals AS m ON a.signal_key = m.document_id
GROUP BY source_product, source_type
ORDER BY recorded_credits DESC
```

These source totals plus scout execution equal the ledger total. Exempt credits are already included.
Do not add signal metadata totals, report detail totals, or scout `spend_credits` to them.

## Spend by scout

```sql
SELECT
    r.skill_name AS scout,
    uniqExact(s.scout_run_id) AS runs,
    sum(s.credits) AS recorded_credits,
    sumIf(s.credits, s.billing_exempt) AS exempt_credits,
    uniqExactIf(s.scout_run_id,
        JSONLength(ifNull(r.emitted_report_ids, '[]')) = 0
        AND JSONLength(ifNull(r.edited_report_ids, '[]')) = 0) AS empty_runs,
    uniqExactIf(s.scout_run_id,
        JSONLength(ifNull(r.edited_report_ids, '[]')) > 0) AS runs_with_edits
FROM system.signal_spend AS s
LEFT JOIN system.scout_runs AS r ON s.scout_run_id = r.id
WHERE s.kind = 'scout_run'
    AND s.finalized_at >= {date_from} AND s.finalized_at < {date_to}
GROUP BY scout
ORDER BY recorded_credits DESC
```

These costs cover execution only. Downstream work remains in the source breakdown, including `signals_scout`.
Use `posthog:scout-runs-retrieve` for a run's findings and `posthog:inbox-reports-retrieve` for a report's lifetime spend; shared scout costs must not be summed across reports.
Runs without receipts are unknown costs, not zero; the monthly tool reports `untracked_scout_run_count`.

## Yield

Yield is the share of settled reports that were resolved.
A report is resolved when its status is `resolved`: someone resolved it, or its pull request merged.
Dismissed reports have the status `suppressed` and do not count.
A report is settled when it was first shown in the inbox at least 14 days ago, so it had time to resolve.

The yield queries read two windows:

- `{date_from}` to `{date_to}`: the spend period, for reports created; take spend separately from the finalized ledger.
- `{yield_from}` to `{date_to}`: the last 60 days, for settled reports. This window can start before spend was tracked.

Estimate cost per resolved report as `spend_usd / (reports_created * settled_rate)`.
Spend and settled reports come from different windows, so this is an estimate. Say so.

HogQL does not allow a function call in a join condition, so each subquery converts the report id to a string first.

### Yield by signal source

```sql
SELECT
    b.source_product AS source_product,
    b.source_type AS source_type,
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
        argMax(JSONExtractString(metadata, 'report_id'), inserted_at) AS report_id
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
GROUP BY source_product, source_type
ORDER BY reports_created DESC
```

A report with signals from several sources counts once under each source.
These are signal-arrival cohorts, separate from finalized usage. Do not sum their report counts as a project total.

### Yield by scout

```sql
SELECT
    e.scout AS scout,
    uniqExactIf(e.report_id, e.created_at >= {date_from}) AS reports_created,
    uniqExactIf(e.report_id, r.settled = 1) AS settled_reports,
    uniqExactIf(e.report_id, r.settled = 1 AND r.status = 'resolved') AS settled_resolved
FROM (
    SELECT
        skill_name AS scout,
        created_at,
        arrayJoin(JSONExtract(ifNull(emitted_report_ids, '[]'), 'Array(String)')) AS report_id
    FROM system.scout_runs
    WHERE created_at >= {yield_from}
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
A scout that mostly edits existing reports shows little yield here, so check `runs_with_edits` in "Spend by scout" before you judge it.
A scout that writes digests or sends findings to Slack may resolve nothing and still be useful. Ask the user before you recommend pausing one.

## Breakdown inside a source

Reuse "Spend by signal source": add `part` to its final `SELECT` and `GROUP BY` using the expressions below with `m.metadata`, and filter the final result to the requested source.
This preserves processing, research, and implementation attribution without copying cumulative metadata spend.

| Source                                   | Expression for `part`                                                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `replay_vision`                          | `JSONExtractString(metadata, 'extra', 'scanner_name')`                                                                    |
| `error_tracking`                         | `JSONExtractString(metadata, 'source_type')` (`issue_created`, `issue_reopened`, `issue_spiking`)                         |
| `llm_analytics`                          | `JSONExtractString(metadata, 'extra', 'evaluation_name')`                                                                 |
| `analytics` with `anomaly_investigation` | `JSONExtractString(metadata, 'extra', 'alert_name')`                                                                      |
| `conversations`                          | `concat(JSONExtractString(metadata, 'extra', 'channel_source'), ' / ', JSONExtractString(metadata, 'extra', 'priority'))` |
| `pganalyze`                              | `JSONExtractString(metadata, 'extra', 'severity')`                                                                        |
| `google_search_console`                  | `JSONExtractString(metadata, 'extra', 'page')`                                                                            |

For part-level yield, add the same expression inside `argMax(..., inserted_at) AS part` in "Yield by signal source" and group by it too. Join the separate spend and yield results by source and part when presenting them.
A source whose parts are each small (under about $5 a month) has nothing worth narrowing. Say that, and move on.
