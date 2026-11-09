# Spend queries

Read the placeholders and HogQL rules in [queries.md](queries.md) first.

## First receipt

Usage history starts no earlier than October 1, 2026, and a project's first receipt can be later.
Check this before you compare months or estimate a run rate. A month that starts before the first receipt is a partial month.

```sql
SELECT min(finalized_at) AS first_receipt, count() AS receipts
FROM system.signal_spend
WHERE finalized_at IS NOT NULL
```

## Spend by day

```sql
SELECT
    toDate(toTimeZone(finalized_at, 'UTC')) AS day,
    kind,
    sum(credits) AS recorded_credits,
    sumIf(credits, billing_exempt) AS exempt_credits,
    countIf(accounting_failed) AS incomplete_records
FROM system.signal_spend
WHERE finalized_at >= {date_from} AND finalized_at < {date_to}
GROUP BY day, kind
ORDER BY day, kind
```

This includes signal processing, research, repository selection, scout execution, and automatic implementation exactly once.
A fix that a person starts from a report is metered as PostHog AI, so it has no record here.
For individual work, select `id`, `signal_id`, `scout_run_id`, `report_id`, `kind`, `credits`, and `billing_exempt` with the same bounds.
For unsettled work created in the period, use `finalized_at IS NULL AND created_at >= {date_from} AND created_at < {date_to}` instead. Keep its credits separate; `accounting_failed` can describe running work.

## Spend by signal source

This reproduces source attribution, including implementation via the report's current triggering signal.
Keep the left joins and null-source group so missing metadata or deleted reports do not remove spend.
Do not filter signal metadata by arrival date: older signals can incur costs this month.

```sql
SELECT
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_product'), '') AS source_product,
    nullIf(JSONExtractString(ifNull(m.metadata, '{}'), 'source_type'), '') AS source_type,
    sum(a.credits) AS recorded_credits,
    sumIf(a.credits, a.billing_exempt) AS exempt_credits,
    sumIf(a.credits, a.kind = 'ad-hoc') AS processing_credits,
    sumIf(a.credits, a.kind IN ('research', 'repo_selection')) AS research_credits,
    sumIf(a.credits, a.kind IN ('reviewer_triggered_implementation', 'scout_triggered_implementation')) AS implementation_credits
FROM (
    SELECT
        s.credits AS credits,
        s.billing_exempt AS billing_exempt,
        s.kind AS kind,
        if(s.report_key != '', r.trigger_key, s.signal_key) AS signal_key
    FROM (
        SELECT
            credits, billing_exempt, kind,
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
GROUP BY source_product, source_type
ORDER BY recorded_credits DESC
```

These source totals plus scout execution equal the ledger total. Exempt credits are already included.
Do not add signal metadata totals, report detail totals, or scout `spend_credits` to them.

## Spend by scout

```sql
SELECT
    r.skill_name AS scout,
    uniqExact(s.run_key) AS runs,
    sum(s.credits) AS recorded_credits,
    sumIf(s.credits, s.billing_exempt) AS exempt_credits,
    uniqExactIf(s.run_key,
        JSONLength(ifNull(r.emitted_report_ids, '[]')) = 0
        AND JSONLength(ifNull(r.edited_report_ids, '[]')) = 0) AS empty_runs,
    sumIf(s.credits,
        JSONLength(ifNull(r.emitted_report_ids, '[]')) = 0
        AND JSONLength(ifNull(r.edited_report_ids, '[]')) = 0) AS empty_run_credits,
    uniqExactIf(s.run_key,
        JSONLength(ifNull(r.edited_report_ids, '[]')) > 0) AS runs_with_edits
FROM (
    SELECT toString(scout_run_id) AS run_key, credits, billing_exempt
    FROM system.signal_spend
    WHERE kind = 'scout_run'
        AND finalized_at >= {date_from} AND finalized_at < {date_to}
) AS s
LEFT JOIN (
    SELECT toString(id) AS rid, skill_name, emitted_report_ids, edited_report_ids
    FROM system.scout_runs
    WHERE created_at >= {date_from} - INTERVAL 7 DAY
) AS r ON s.run_key = r.rid
GROUP BY scout
ORDER BY recorded_credits DESC
```

These costs cover execution only. Downstream work remains in the source breakdown, including `signals_scout`.
Use `posthog:scout-runs-retrieve` for a run's findings and `posthog:inbox-reports-retrieve` for a report's lifetime spend; shared scout costs must not be summed across reports.
Runs without receipts are unknown costs, not zero; the monthly tool reports `untracked_scout_run_count`.
A run that a pre-check skipped has no run row and no receipt, so it is neither a cost nor a missing record.
