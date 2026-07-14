// Per-workflow CI health table, shared by the Workflows tab and the repo hub.

import { useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { withScope } from '../lib/scope'
import { WorkflowHealthRow, workflowFailureSeries } from '../scenes/engineeringAnalyticsLogic'
import { BillableBadge } from './BillableBadge'
import { FailureSparkline } from './FailureSparkline'
import { DeltaBadge, pointChange } from './MetricTile'

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
    /** Column sort override. Default (null) keeps the rows' failing-first-then-name order — the one
     *  convention shared with the PR page; pass a column to sort by it instead. */
    defaultSorting?: { columnKey: string; order: 1 | -1 } | null
    /** Show the billable cost column (needs per-workflow cost on the rows). */
    showCost?: boolean
    /** Rows per page — the shared 25 by default; the hub passes a small page to stay scannable. */
    pageSize?: number
    emptyState?: ReactNode
    dataAttr?: string
    /** Drop the table's own border when it sits inside a LemonCard (the hub) — avoids a double frame. */
    embedded?: boolean
    /** Hub preview variant: a focused column set (status · pass rate · Δ · cost · health) with the health
     *  sparkline given room. The full run/p50/p95/re-runs/last-failure columns stay on the Workflows tab. */
    compact?: boolean
}

// The compact (hub preview) column set, in display order: the health-and-cost story with pass rate next
// to its own trend (Δ). Cost only appears when showCost adds it. Headers stay intact.
const COMPACT_COLUMN_ORDER = ['workflowName', 'status', 'successRate', 'successRateDelta', 'cost', 'trend']

export function WorkflowHealthTable({
    rows,
    loading,
    sourceId,
    defaultSorting = null,
    showCost = false,
    pageSize = 25,
    emptyState,
    dataAttr = 'engineering-analytics-workflow-table',
    embedded = false,
    compact = false,
}: WorkflowHealthTableProps): JSX.Element {
    const { searchParams } = useValues(router)
    // Each row opens the workflow's runs page, carrying the active window/branch scope + source so the
    // drill-down doesn't silently widen to all branches.
    const rowUrl = (row: WorkflowHealthRow): string =>
        withScope(
            urls.engineeringAnalyticsWorkflowRuns(row.repoOwner, row.repoName, row.workflowName),
            searchParams,
            sourceId
        )
    // Failing workflows first — the order a reviewer triages in — then everything else alphabetically by
    // name. The one convention shared with the PR page; a passed defaultSorting still overrides on click.
    const orderedRows = [...rows].sort(
        (a, b) =>
            Number(b.latestRunFailed === true) - Number(a.latestRunFailed === true) ||
            a.workflowName.localeCompare(b.workflowName)
    )
    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
            sorter: (a, b) => a.workflowName.localeCompare(b.workflowName),
            render: (_, row) => (
                <div className="flex items-center gap-2">
                    <Link to={rowUrl(row)} className="font-medium" onClick={(e) => e.stopPropagation()}>
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

    // Compact keeps the focused column set (in COMPACT_COLUMN_ORDER) and lets the health sparkline breathe.
    const displayColumns = compact
        ? COMPACT_COLUMN_ORDER.map((key) => columns.find((column) => String(column.key) === key))
              .filter((column): column is (typeof columns)[number] => column !== undefined)
              .map((column) => (column.key === 'trend' ? { ...column, title: 'Health', width: 220 } : column))
        : columns

    return (
        <LemonTable
            data-attr={dataAttr}
            size="small"
            embedded={embedded}
            columns={displayColumns}
            dataSource={orderedRows}
            rowKey={(row) => `${row.repoOwner}/${row.repoName}:${row.workflowName}`}
            // De-emphasize workflows with nothing settled — no pass/fail signal to read.
            rowClassName={(row) => cn('cursor-pointer', row.successRate === null && 'opacity-60')}
            onRow={(row) => {
                const url = rowUrl(row)
                return {
                    // Inner links (the workflow name) keep their own behavior.
                    onClick: (e: React.MouseEvent) => {
                        if ((e.target as HTMLElement).closest('a, button')) {
                            return
                        }
                        if (e.metaKey || e.ctrlKey) {
                            e.preventDefault()
                            newInternalTab(url)
                        } else {
                            router.actions.push(url)
                        }
                    },
                    onAuxClick: (e: React.MouseEvent) => {
                        if (e.button === 1 && !(e.target as HTMLElement).closest('a, button')) {
                            e.preventDefault()
                            newInternalTab(url)
                        }
                    },
                }
            }}
            loading={loading}
            useURLForSorting={false}
            defaultSorting={defaultSorting}
            pagination={{ pageSize }}
            emptyState={emptyState ?? 'No workflow runs.'}
            nouns={['workflow', 'workflows']}
        />
    )
}
