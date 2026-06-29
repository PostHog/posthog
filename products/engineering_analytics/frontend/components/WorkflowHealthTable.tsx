// Per-workflow CI health table, shared by the Workflows tab (time-bucketed) and the PR detail page
// (per-push buckets, rows expandable to runs). Only the bucket axis and row expansion differ per caller.

import { combineUrl } from 'kea-router'
import { ReactNode } from 'react'

import { IconTrending } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import type { ExpandableConfig } from 'lib/lemon-ui/LemonTable/types'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import {
    WorkflowHealthRow,
    WorkflowTrendDirection,
    workflowFailureSeries,
    workflowFailureTrend,
} from '../scenes/engineeringAnalyticsLogic'
import { BillableBadge } from './BillableBadge'
import { FailureSparkline } from './FailureSparkline'
import { CI_GRID } from './runTables'

// Floor on bar slots for push-bucketed sparklines (PR view) so a single push stays narrow, but low
// enough that 2-3 pushes read as separate bars. Time-bucketed sparklines (Workflows tab) fill.
const PUSH_MIN_SLOTS = 10

function formatSeconds(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds)
}

function formatRate(rate: number | null): string {
    return rate == null ? '—' : `${humanFriendlyNumber(rate * 100)}%`
}

/** Color only what needs attention — red rare, amber occasional, everything else plain. */
function successRateClass(rate: number | null): string {
    if (rate == null) {
        return 'text-secondary'
    }
    if (rate < 0.8) {
        return 'font-semibold text-danger'
    }
    if (rate < 0.9) {
        return 'font-medium text-warning'
    }
    return ''
}

/** Stable per-name color so each workflow keeps the same dot across renders and sorts. */
function WorkflowDot({ name }: { name: string }): JSX.Element {
    const palette = getSeriesColorPalette()
    let hash = 0
    for (let i = 0; i < name.length; i++) {
        hash = (hash * 31 + name.charCodeAt(i)) | 0
    }
    const color = palette[Math.abs(hash) % palette.length]
    return <span className="inline-block h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
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

function TrendArrow({ direction }: { direction: WorkflowTrendDirection }): JSX.Element {
    // Arrow tracks health, not failures: rising failures = declining health = red down arrow, and vice versa.
    if (direction === 'up') {
        return (
            <Tooltip title="Health declining — failures rising">
                <IconTrendingDown className="text-danger shrink-0" />
            </Tooltip>
        )
    }
    if (direction === 'down') {
        return (
            <Tooltip title="Health improving — failures falling">
                <IconTrending className="text-success shrink-0" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Health steady — no change in failures">
            <IconTrendingFlat className="text-muted shrink-0" />
        </Tooltip>
    )
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
    emptyState,
    dataAttr = 'engineering-analytics-workflow-table',
}: WorkflowHealthTableProps): JSX.Element {
    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
            sorter: (a, b) => a.workflowName.localeCompare(b.workflowName),
            render: (_, row) => (
                <div className="flex items-center gap-2">
                    <WorkflowDot name={row.workflowName} />
                    <Link
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsWorkflowRuns(row.repoOwner, row.repoName, row.workflowName),
                                sourceId ? { source: sourceId } : {}
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
            width: CI_GRID.status,
            // Failing first when sorted: failing (2) > unknown (1) > passing (0).
            sorter: (a, b) => statusRank(a.latestRunFailed) - statusRank(b.latestRunFailed),
            render: (_, row) => <StatusTag failed={row.latestRunFailed} conclusion={row.latestRunConclusion} />,
        },
        {
            title: 'Runs',
            key: 'runCount',
            width: CI_GRID.runs,
            align: 'right',
            sorter: (a, b) => a.runCount - b.runCount,
            render: (_, row) => <span className="text-xs tabular-nums">{humanFriendlyNumber(row.runCount)}</span>,
        },
        {
            title: 'Success rate',
            key: 'successRate',
            width: CI_GRID.successRate,
            align: 'right',
            sorter: (a, b) => (a.successRate ?? -1) - (b.successRate ?? -1),
            render: (_, row) => (
                <span className={cn('text-xs tabular-nums', successRateClass(row.successRate))}>
                    {formatRate(row.successRate)}
                </span>
            ),
        },
        ...((showCost
            ? [
                  {
                      title: 'Cost',
                      key: 'cost',
                      width: CI_GRID.cost,
                      align: 'right',
                      sorter: (a, b) => (a.estimatedCostUsd ?? -1) - (b.estimatedCostUsd ?? -1),
                      render: (_, row) => (
                          <BillableBadge minutes={row.billableMinutes} costUsd={row.estimatedCostUsd} />
                      ),
                  },
              ]
            : []) as LemonTableColumns<WorkflowHealthRow>),
        {
            title: 'Health',
            key: 'trend',
            // Pinned so the layout doesn't shift when sorting reorders rows with and without history.
            width: CI_GRID.health,
            render: function RenderTrend(_, row) {
                if (row.buckets.length === 0) {
                    return <span className="text-xs text-secondary">—</span>
                }
                const { completed, failures, labels } = workflowFailureSeries(row.buckets, row.granularity)
                return (
                    <div className="flex items-center gap-2">
                        <FailureSparkline
                            className="flex-1"
                            completed={completed}
                            failures={failures}
                            labels={labels}
                            ariaLabel={`${row.workflowName} failure history`}
                            // Push buckets are few — keep bars narrow and right-aligned instead of fat.
                            minSlots={row.granularity === 'push' ? PUSH_MIN_SLOTS : undefined}
                        />
                        <TrendArrow direction={workflowFailureTrend(row.buckets)} />
                    </div>
                )
            },
        },
        {
            title: 'p50',
            key: 'p50Seconds',
            width: CI_GRID.p50,
            align: 'right',
            sorter: (a, b) => (a.p50Seconds ?? -1) - (b.p50Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap tabular-nums">{formatSeconds(row.p50Seconds)}</span>
            ),
        },
        {
            title: 'p95',
            key: 'p95Seconds',
            width: CI_GRID.p95,
            align: 'right',
            sorter: (a, b) => (a.p95Seconds ?? -1) - (b.p95Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap tabular-nums">{formatSeconds(row.p95Seconds)}</span>
            ),
        },
        {
            title: 'Last failure',
            key: 'lastFailureAt',
            width: CI_GRID.lastFailure,
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
            // Fixed layout honors the CI_GRID widths exactly so nested run/job tables line their columns up.
            className="[&_table]:table-fixed"
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
            pagination={{ pageSize: 50 }}
            emptyState={emptyState ?? 'No workflow runs.'}
            nouns={['workflow', 'workflows']}
        />
    )
}
