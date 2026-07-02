// The workflow page's jobs table: one row per de-sharded job name (the backend strips the matrix
// "(G/N)" suffix with the same rule the frontend's jobGroups uses), with the per-job numbers that
// explain a workflow's behavior — run share (conditional jobs skip), queue wait, duration spread,
// failure rate, retry pressure, and billable cost. Jobs never get standalone pages; a job always needs
// its run as context, so drill-downs happen by expanding a run below.

import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { WorkflowJobAggregateApi } from '../generated/api.schemas'
import { compactUsd, percent } from '../lib/format'
import { BillableBadge } from './BillableBadge'
import { RangeBar } from './RangeBar'

function formatSeconds(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds)
}

export function JobAggregatesTable({
    aggregates,
    loading,
    totalCostUsd,
}: {
    aggregates: WorkflowJobAggregateApi[]
    loading: boolean
    /** The workflow's total window cost — the denominator of each job's cost share. */
    totalCostUsd: number | null
}): JSX.Element {
    // One scale across rows so duration compares visually down the column.
    const maxP95 = Math.max(...aggregates.map((row) => row.p95_seconds ?? 0), 1)

    return (
        <LemonTable<WorkflowJobAggregateApi>
            dataSource={aggregates}
            loading={loading}
            size="small"
            rowKey={(row) => row.job_name}
            useURLForSorting={false}
            columns={[
                {
                    title: 'Job',
                    key: 'job',
                    sorter: (a, b) => a.job_name.localeCompare(b.job_name),
                    render: (_, row) => (
                        <span className="flex items-center gap-2">
                            <span className="font-mono text-xs">{row.job_name}</span>
                            {row.shard_count > 1 && <LemonTag type="muted">×{row.shard_count} matrix</LemonTag>}
                        </span>
                    ),
                },
                {
                    title: 'Runs in',
                    key: 'runShare',
                    align: 'right',
                    tooltip: 'Share of workflow runs this job actually ran in — conditional jobs skip runs.',
                    sorter: (a, b) => (a.run_share ?? -1) - (b.run_share ?? -1),
                    render: (_, row) => (
                        <span
                            className={
                                row.run_share != null && row.run_share < 0.995
                                    ? 'text-xs tabular-nums text-secondary'
                                    : 'text-xs tabular-nums'
                            }
                        >
                            {row.run_share != null ? `${percent(Math.min(1, row.run_share))} of runs` : '—'}
                        </span>
                    ),
                },
                {
                    title: 'Queue p50',
                    key: 'queue',
                    align: 'right',
                    tooltip: 'Median created → started wait — where runner-capacity problems hide.',
                    sorter: (a, b) => (a.queue_p50_seconds ?? -1) - (b.queue_p50_seconds ?? -1),
                    render: (_, row) => (
                        <span className="text-xs tabular-nums text-tertiary">
                            {formatSeconds(row.queue_p50_seconds)}
                        </span>
                    ),
                },
                {
                    title: 'p50 → p95',
                    key: 'duration',
                    align: 'right',
                    sorter: (a, b) => (a.p50_seconds ?? -1) - (b.p50_seconds ?? -1),
                    render: (_, row) =>
                        row.p50_seconds == null ? (
                            <span className="text-xs text-secondary">—</span>
                        ) : (
                            <span className="inline-block text-right">
                                <span className="text-xs tabular-nums whitespace-nowrap">
                                    {formatSeconds(row.p50_seconds)}{' '}
                                    <span className="text-tertiary">→ {formatSeconds(row.p95_seconds)}</span>
                                </span>
                                <RangeBar
                                    fraction={(row.p50_seconds ?? 0) / maxP95}
                                    tickFraction={row.p95_seconds != null ? row.p95_seconds / maxP95 : null}
                                    className="mt-0.5 block w-20"
                                    tooltip={`p50 ${formatSeconds(row.p50_seconds)} (fill) → p95 ${formatSeconds(row.p95_seconds)} (tick), scaled to the slowest job`}
                                />
                            </span>
                        ),
                },
                {
                    title: 'Failure rate',
                    key: 'failureRate',
                    align: 'right',
                    tooltip: 'Decisive failures (failure / timed out) over completed job instances.',
                    sorter: (a, b) => (a.failure_rate ?? -1) - (b.failure_rate ?? -1),
                    render: (_, row) => (
                        <span
                            className={
                                (row.failure_rate ?? 0) > 0.05
                                    ? 'text-xs font-semibold tabular-nums text-danger'
                                    : 'text-xs tabular-nums'
                            }
                        >
                            {row.failure_rate != null ? percent(row.failure_rate) : '—'}
                        </span>
                    ),
                },
                {
                    title: 'Retries',
                    key: 'retries',
                    align: 'right',
                    tooltip: 'Job instances that ran on a 2nd+ run attempt — retry pressure is a flakiness proxy.',
                    sorter: (a, b) => a.retry_job_count - b.retry_job_count,
                    render: (_, row) => (
                        <span className="text-xs tabular-nums">{humanFriendlyNumber(row.retry_job_count)}</span>
                    ),
                },
                {
                    title: 'Cost',
                    key: 'cost',
                    align: 'right',
                    sorter: (a, b) => (a.estimated_cost_usd ?? -1) - (b.estimated_cost_usd ?? -1),
                    render: (_, row) => {
                        if (row.estimated_cost_usd == null) {
                            return <span className="text-xs text-secondary">Free</span>
                        }
                        const share = totalCostUsd && totalCostUsd > 0 ? row.estimated_cost_usd / totalCostUsd : null
                        return (
                            <Tooltip
                                title={
                                    <BillableBadge minutes={row.billable_minutes} costUsd={row.estimated_cost_usd} />
                                }
                            >
                                <span className="text-xs tabular-nums whitespace-nowrap">
                                    {compactUsd(row.estimated_cost_usd)}
                                    {share != null && (
                                        <span className="ml-1 text-tertiary">{Math.round(share * 100)}%</span>
                                    )}
                                </span>
                            </Tooltip>
                        )
                    },
                },
            ]}
            defaultSorting={{ columnKey: 'cost', order: -1 }}
            pagination={{ pageSize: 50 }}
            emptyState="No jobs in the window — the job-level source may not be synced."
            nouns={['job', 'jobs']}
        />
    )
}
