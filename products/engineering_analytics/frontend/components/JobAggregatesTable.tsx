// One row per de-sharded job name (the backend strips the matrix "(G/N)" suffix with the same rule as
// jobGroups). Jobs get no standalone pages — a job always needs its run as context.

import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { WorkflowJobAggregateApi } from '../generated/api.schemas'
import { compactUsd, percent } from '../lib/format'
import { BillableBadge } from './BillableBadge'

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
                    tooltip: 'Share of workflow runs this job ran in. Below 100% means the job is conditional.',
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
                    tooltip: 'Median wait from job created to started. Long waits point to runner capacity problems.',
                    sorter: (a, b) => (a.queue_p50_seconds ?? -1) - (b.queue_p50_seconds ?? -1),
                    render: (_, row) => (
                        <span className="text-xs tabular-nums text-tertiary">
                            {formatSeconds(row.queue_p50_seconds)}
                        </span>
                    ),
                },
                {
                    title: 'P50',
                    key: 'duration',
                    align: 'right',
                    tooltip: 'Median job duration over completed instances.',
                    sorter: (a, b) => (a.p50_seconds ?? -1) - (b.p50_seconds ?? -1),
                    render: (_, row) => (
                        <span className="text-xs tabular-nums whitespace-nowrap">{formatSeconds(row.p50_seconds)}</span>
                    ),
                },
                {
                    title: 'P95',
                    key: 'p95',
                    align: 'right',
                    tooltip: '95th-percentile job duration over completed instances.',
                    sorter: (a, b) => (a.p95_seconds ?? -1) - (b.p95_seconds ?? -1),
                    render: (_, row) => (
                        <span className="text-xs tabular-nums whitespace-nowrap text-secondary">
                            {formatSeconds(row.p95_seconds)}
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
                    tooltip:
                        'Job instances that ran on a second or later attempt. Frequent re-runs usually point to flaky checks.',
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
            emptyState="No jobs in the window. The job-level source may not be synced."
            nouns={['job', 'jobs']}
        />
    )
}
