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

/** The p50→p95 duration spread as a small bar, scaled to the slowest job so rows compare at a glance.
 *  Solid segment reaches the median (p50); the lighter extension is the tail out to p95 — a long light
 *  tail is a job whose worst case dwarfs its typical case. Two raw numbers ("3m … 20m") don't show that. */
function DurationSpread({ p50, p95, max }: { p50: number | null; p95: number | null; max: number }): JSX.Element {
    if (p50 == null && p95 == null) {
        return <span className="text-xs text-tertiary">—</span>
    }
    const tail = p95 ?? p50 ?? 0
    const median = p50 ?? tail
    const tailPct = Math.min(100, Math.max(2, (tail / max) * 100))
    const medianPct = Math.min(100, Math.max(1, (median / max) * 100))
    return (
        <Tooltip title={`median ${formatSeconds(p50)} · p95 ${formatSeconds(p95)}`}>
            <div className="flex items-center gap-2">
                <div className="relative h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-fill-tertiary">
                    <span
                        className="absolute inset-y-0 left-0 rounded-full opacity-30"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${tailPct}%`, backgroundColor: 'var(--data-color-1)' }}
                    />
                    <span
                        className="absolute inset-y-0 left-0 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${medianPct}%`, backgroundColor: 'var(--data-color-1)' }}
                    />
                </div>
                <span className="text-xs tabular-nums whitespace-nowrap text-tertiary">{formatSeconds(p50)}</span>
            </div>
        </Tooltip>
    )
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
    // Scale every duration bar to the slowest job's p95, so bar lengths compare directly across rows.
    const maxP95 = Math.max(1, ...aggregates.map((a) => a.p95_seconds ?? a.p50_seconds ?? 0))
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
                    title: 'Duration',
                    key: 'duration',
                    tooltip:
                        'Median (p50) out to 95th-percentile duration over successful instances, as a bar scaled to the slowest job. The solid part reaches the median; the light tail runs out to p95.',
                    sorter: (a, b) => (a.p50_seconds ?? -1) - (b.p50_seconds ?? -1),
                    render: (_, row) => <DurationSpread p50={row.p50_seconds} p95={row.p95_seconds} max={maxP95} />,
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
                    tooltip:
                        'Estimated cost over billable (self-hosted) runners. "—" when there is no billable figure: GitHub-hosted, an unrecognized runner, or no finished instance yet.',
                    sorter: (a, b) => (a.estimated_cost_usd ?? -1) - (b.estimated_cost_usd ?? -1),
                    render: (_, row) => {
                        if (row.estimated_cost_usd == null) {
                            return <span className="text-xs text-tertiary">—</span>
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
                                    {share != null && <span className="ml-1 text-tertiary">{percent(share)}</span>}
                                </span>
                            </Tooltip>
                        )
                    },
                },
            ]}
            defaultSorting={{ columnKey: 'cost', order: -1 }}
            pagination={{ pageSize: 25 }}
            emptyState="No jobs in the window. The job-level source may not be synced."
            nouns={['job', 'jobs']}
        />
    )
}
