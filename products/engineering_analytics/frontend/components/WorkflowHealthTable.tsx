// Per-workflow CI health table, shared by the Workflows tab (time-bucketed) and the PR detail page
// (per-push buckets, rows expandable to runs). Only the bucket axis and row expansion differ per caller.

import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { ReactNode } from 'react'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { ExpandableConfig } from 'lib/lemon-ui/LemonTable/types'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { WorkflowHealthRow, workflowFailureSeries } from '../scenes/engineeringAnalyticsLogic'
import { BillableBadge } from './BillableBadge'
import { FailureSparkline } from './FailureSparkline'
import { DeltaBadge, pointChange } from './MetricTile'

// Floor on bar slots for push-bucketed sparklines (PR view) so a single push stays narrow, but low
// enough that 2-3 pushes read as separate bars. Time-bucketed sparklines (Workflows tab) fill.
const PUSH_MIN_SLOTS = 10

function formatSeconds(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds)
}

function formatRate(rate: number | null): string {
    return rate == null ? '—' : `${humanFriendlyNumber(rate * 100)}%`
}

/** Color only what needs attention — red rare, amber occasional, everything else plain. A low rate
 *  without any decisive failure (skip/cancel-heavy workflows) stays plain: nothing is broken. */
function successRateClass(rate: number | null, hasFailures: boolean): string {
    if (rate == null) {
        return 'text-secondary'
    }
    if (!hasFailures) {
        return ''
    }
    if (rate < 0.8) {
        return 'font-semibold text-danger'
    }
    if (rate < 0.9) {
        return 'font-medium text-warning'
    }
    return ''
}

/** Sort key so a Status sort surfaces failing workflows first. */
function statusRank(failed: boolean | null): number {
    if (failed === true) {
        return 2
    }
    return failed === null ? 1 : 0
}

function StatusTag({ failed, conclusion }: { failed: boolean | null; conclusion: string | null }): JSX.Element {
    if (failed === null) {
        // Nothing has completed in the window — no pass/fail signal to show.
        return <span className="text-xs text-secondary">—</span>
    }
    if (failed) {
        return <LemonTag type="danger">Failing</LemonTag>
    }
    if (conclusion === 'success' || conclusion == null) {
        return <LemonTag type="success">Passing</LemonTag>
    }
    // Latest run neither a decisive failure nor a clean success — show the raw outcome muted, not a
    // misleading green "Passing".
    return <LemonTag type="muted">{capitalizeFirstLetter(conclusion.replace('_', ' '))}</LemonTag>
}

export interface WorkflowHealthTableProps {
    rows: WorkflowHealthRow[]
    loading?: boolean
    /** Threaded into the Workflow-name link so it preserves the active source. */
    sourceId?: string | null
    /** Optional row expansion (the PR page expands a workflow to its runs). */
    expandable?: ExpandableConfig<WorkflowHealthRow>
    /** Default column sort. Alphabetical by workflow name by default; click Status for failing-first. */
    defaultSorting?: { columnKey: string; order: 1 | -1 }
    /** Show the billable cost column (needs per-workflow cost on the rows; PR page only for now). */
    showCost?: boolean
    /** Rows per page — 50 by default; the hub passes a small page to stay scannable. */
    pageSize?: number
    emptyState?: ReactNode
    dataAttr?: string
}

export function WorkflowHealthTable({
    rows,
    loading,
    sourceId,
    expandable,
    defaultSorting = { columnKey: 'workflowName', order: 1 },
    showCost = false,
    pageSize = 50,
    emptyState,
    dataAttr = 'engineering-analytics-workflow-table',
}: WorkflowHealthTableProps): JSX.Element {
    const { searchParams } = useValues(router)
    // Carry the active window/branch scope into the drill-down; without `q` the detail page would
    // silently widen to all branches.
    const windowParams: Record<string, string> = {
        ...(searchParams.date_from ? { date_from: searchParams.date_from } : {}),
        ...(searchParams.date_to ? { date_to: searchParams.date_to } : {}),
        ...(searchParams.q ? { q: searchParams.q } : {}),
    }
    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
            sorter: (a, b) => a.workflowName.localeCompare(b.workflowName),
            render: (_, row) => (
                <div className="flex items-center gap-2">
                    <Link
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsWorkflowRuns(row.repoOwner, row.repoName, row.workflowName),
                                { ...windowParams, ...(sourceId ? { source: sourceId } : {}) }
                            ).url
                        }
                        className="font-medium"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {row.workflowName}
                    </Link>
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 90,
            // Failing first when sorted: failing (2) > unknown (1) > passing (0).
            sorter: (a, b) => statusRank(a.latestRunFailed) - statusRank(b.latestRunFailed),
            render: (_, row) => <StatusTag failed={row.latestRunFailed} conclusion={row.latestRunConclusion} />,
        },
        {
            title: 'Runs',
            key: 'runCount',
            width: 60,
            align: 'right',
            sorter: (a, b) => a.runCount - b.runCount,
            render: (_, row) => <span className="text-xs tabular-nums">{humanFriendlyNumber(row.runCount)}</span>,
        },
        {
            title: 'Pass rate',
            key: 'successRate',
            width: 96,
            align: 'right',
            sorter: (a, b) => (a.successRate ?? -1) - (b.successRate ?? -1),
            render: (_, row) => (
                <span
                    className={cn(
                        'text-xs tabular-nums',
                        successRateClass(
                            row.successRate,
                            row.buckets.some((bucket) => bucket.failures > 0)
                        )
                    )}
                >
                    {formatRate(row.successRate)}
                </span>
            ),
        },
        ...((showCost
            ? [
                  {
                      title: 'Cost',
                      tooltip:
                          "CI minutes spent (each job's time summed, so parallel jobs add up) and the estimated cost at the reference rate. This is compute time, not wall-clock run time. Still-running jobs are excluded, so the figure can rise as they settle.",
                      key: 'cost',
                      width: 130,
                      align: 'right',
                      sorter: (a, b) => (a.estimatedCostUsd ?? -1) - (b.estimatedCostUsd ?? -1),
                      render: (_, row) => (
                          <BillableBadge minutes={row.billableMinutes} costUsd={row.estimatedCostUsd} />
                      ),
                  },
              ]
            : []) as LemonTableColumns<WorkflowHealthRow>),
        {
            title: 'Δ',
            key: 'successRateDelta',
            width: 76,
            align: 'right',
            tooltip: 'Success-rate change in percentage points vs the equal-length window before this one.',
            sorter: (a, b) =>
                (pointChange(a.successRate, a.successRatePrev) ?? -Infinity) -
                (pointChange(b.successRate, b.successRatePrev) ?? -Infinity),
            render: (_, row) => {
                const delta = pointChange(row.successRate, row.successRatePrev)
                return delta == null ? (
                    <span className="text-xs text-secondary">—</span>
                ) : (
                    <DeltaBadge value={delta} unit="pp" />
                )
            },
        },
        {
            title: 'P50',
            key: 'p50Seconds',
            width: 88,
            align: 'right',
            tooltip: 'Median run duration (wall-clock) over completed runs.',
            sorter: (a, b) => (a.p50Seconds ?? -1) - (b.p50Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs tabular-nums whitespace-nowrap">{formatSeconds(row.p50Seconds)}</span>
            ),
        },
        {
            title: 'P95',
            key: 'p95Seconds',
            width: 88,
            align: 'right',
            tooltip: '95th-percentile run duration (wall-clock) over completed runs.',
            sorter: (a, b) => (a.p95Seconds ?? -1) - (b.p95Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs tabular-nums whitespace-nowrap text-secondary">
                    {formatSeconds(row.p95Seconds)}
                </span>
            ),
        },
        {
            title: 'Re-runs',
            key: 'rerunCycles',
            width: 76,
            align: 'right',
            tooltip: 'Runs with attempt > 1 in the window. Frequent re-runs usually point to flaky checks.',
            sorter: (a, b) => (a.rerunCycles ?? 0) - (b.rerunCycles ?? 0),
            render: (_, row) => (
                <span
                    className={cn(
                        'text-xs tabular-nums',
                        (row.rerunCycles ?? 0) > 50 && 'font-semibold text-warning-dark'
                    )}
                >
                    {row.rerunCycles ?? '—'}
                </span>
            ),
        },
        {
            title: 'Health',
            key: 'trend',
            // Pinned so the layout doesn't shift when sorting reorders rows with and without history.
            width: 132,
            render: function RenderTrend(_, row) {
                if (row.buckets.length === 0) {
                    return <span className="text-xs text-secondary">—</span>
                }
                const { completed, failures, labels } = workflowFailureSeries(row.buckets, row.granularity)
                return (
                    <FailureSparkline
                        completed={completed}
                        failures={failures}
                        labels={labels}
                        ariaLabel={`${row.workflowName} failure history`}
                        // Push buckets are few — keep bars narrow and right-aligned instead of fat.
                        minSlots={row.granularity === 'push' ? PUSH_MIN_SLOTS : undefined}
                    />
                )
            },
        },
        {
            title: 'Last failure',
            key: 'lastFailureAt',
            width: 100,
            align: 'right',
            render: (_, row) =>
                row.lastFailureAt ? (
                    <span className="text-xs whitespace-nowrap">
                        <TZLabel time={row.lastFailureAt} />
                    </span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
    ]

    return (
        <LemonTable
            data-attr={dataAttr}
            size="small"
            columns={columns}
            dataSource={rows}
            rowKey={(row) => `${row.repoOwner}/${row.repoName}:${row.workflowName}`}
            // De-emphasize workflows with nothing settled — no pass/fail signal to read.
            rowClassName={(row) => (row.successRate === null ? 'opacity-60' : null)}
            loading={loading}
            useURLForSorting={false}
            defaultSorting={defaultSorting}
            expandable={expandable}
            pagination={{ pageSize }}
            emptyState={emptyState ?? 'No workflow runs.'}
            nouns={['workflow', 'workflows']}
        />
    )
}
