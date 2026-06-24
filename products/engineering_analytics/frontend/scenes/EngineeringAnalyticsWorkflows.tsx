import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconTrending } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { FailureSparkline } from '../components/FailureSparkline'
import {
    WorkflowHealthRow,
    WorkflowTrendDirection,
    engineeringAnalyticsLogic,
    workflowFailureSeries,
    workflowFailureTrend,
} from './engineeringAnalyticsLogic'

// The endpoint caps the window at 366 days, so "All time" and week/month snaps are out.
const WORKFLOW_DATE_OPTIONS = dateMapping.filter(({ key }) =>
    [
        'Custom',
        'Last 24 hours',
        'Last 7 days',
        'Last 14 days',
        'Last 30 days',
        'Last 90 days',
        'Last 180 days',
        'Year to date',
    ].includes(key)
)

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

function StatusTag({ failed }: { failed: boolean | null }): JSX.Element {
    if (failed === null) {
        // Nothing has completed in the window — no pass/fail signal to show.
        return <span className="text-xs text-secondary">—</span>
    }
    return failed ? <LemonTag type="danger">Failing</LemonTag> : <LemonTag type="success">Passing</LemonTag>
}

function TrendArrow({ direction }: { direction: WorkflowTrendDirection }): JSX.Element {
    if (direction === 'up') {
        return (
            <Tooltip title="Failures rising">
                <IconTrending className="text-danger shrink-0" />
            </Tooltip>
        )
    }
    if (direction === 'down') {
        return (
            <Tooltip title="Failures falling">
                <IconTrendingDown className="text-success shrink-0" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title="No change in failures">
            <IconTrendingFlat className="text-muted shrink-0" />
        </Tooltip>
    )
}

export function EngineeringAnalyticsWorkflows(): JSX.Element {
    const {
        workflowHealth,
        workflowHealthLoading,
        notConnected,
        workflowHealthLoadError,
        workflowDateFrom,
        workflowDateTo,
        branchInput,
        appliedBranch,
        sourceId,
    } = useValues(engineeringAnalyticsLogic)
    const { setWorkflowDateRange, setBranchFilter, applyBranchFilter, refresh } = useActions(engineeringAnalyticsLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (workflowHealthLoadError) {
        return <CIAnalyticsLoadError onRetry={refresh} />
    }

    const windowLabel = dateFilterToText(workflowDateFrom, workflowDateTo, 'Last 24 hours') ?? 'Last 24 hours'

    // Stage + apply a branch in one click (the chips). Clicking the active chip clears back to all branches.
    const selectBranch = (branch: string): void => {
        setBranchFilter(branch)
        applyBranchFilter()
    }

    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
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
                    >
                        {row.workflowName}
                    </Link>
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            // Failing first when sorted: failing (2) > unknown (1) > passing (0).
            sorter: (a, b) => statusRank(a.latestRunFailed) - statusRank(b.latestRunFailed),
            render: (_, row) => <StatusTag failed={row.latestRunFailed} />,
        },
        {
            title: 'Runs',
            key: 'runCount',
            align: 'right',
            sorter: (a, b) => a.runCount - b.runCount,
            render: (_, row) => <span className="text-xs tabular-nums">{humanFriendlyNumber(row.runCount)}</span>,
        },
        {
            title: 'Success rate',
            key: 'successRate',
            align: 'right',
            sorter: (a, b) => (a.successRate ?? -1) - (b.successRate ?? -1),
            render: (_, row) => (
                <span className={cn('text-xs tabular-nums', successRateClass(row.successRate))}>
                    {formatRate(row.successRate)}
                </span>
            ),
        },
        {
            title: 'Failures',
            key: 'trend',
            // Pinned so the layout doesn't shift when sorting reorders rows with and without history.
            width: 272,
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
                        />
                        <TrendArrow direction={workflowFailureTrend(row.buckets)} />
                    </div>
                )
            },
        },
        {
            title: 'p50',
            key: 'p50Seconds',
            align: 'right',
            sorter: (a, b) => (a.p50Seconds ?? -1) - (b.p50Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap tabular-nums">{formatSeconds(row.p50Seconds)}</span>
            ),
        },
        {
            title: 'p95',
            key: 'p95Seconds',
            align: 'right',
            sorter: (a, b) => (a.p95Seconds ?? -1) - (b.p95Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap tabular-nums">{formatSeconds(row.p95Seconds)}</span>
            ),
        },
        {
            title: 'Last failure',
            key: 'lastFailureAt',
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
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
                <DateFilter
                    dateFrom={workflowDateFrom}
                    dateTo={workflowDateTo}
                    onChange={setWorkflowDateRange}
                    dateOptions={WORKFLOW_DATE_OPTIONS}
                />
                <LemonInput
                    type="search"
                    size="small"
                    className="w-56"
                    placeholder="Branch: all (e.g. main)"
                    value={branchInput}
                    onChange={setBranchFilter}
                    onPressEnter={applyBranchFilter}
                    onBlur={applyBranchFilter}
                    data-attr="engineering-analytics-branch-filter"
                />
                {/* Quick presets for the default branch. We can't tell main from master without another query,
                    so offer both — clicking the active one clears back to all branches. */}
                {['main', 'master'].map((branch) => (
                    <LemonButton
                        key={branch}
                        size="xsmall"
                        type={appliedBranch === branch ? 'primary' : 'secondary'}
                        onClick={() => selectBranch(appliedBranch === branch ? '' : branch)}
                    >
                        {branch}
                    </LemonButton>
                ))}
            </div>
            <LemonTable
                data-attr="engineering-analytics-workflow-table"
                size="small"
                columns={columns}
                dataSource={workflowHealth}
                rowKey={(row) => `${row.repoOwner}/${row.repoName}:${row.workflowName}`}
                // De-emphasize workflows with nothing settled in the window — no pass/fail signal to read.
                rowClassName={(row) => (row.successRate === null ? 'opacity-60' : null)}
                loading={workflowHealthLoading}
                useURLForSorting={false}
                pagination={{ pageSize: 50 }}
                emptyState={
                    appliedBranch
                        ? `No workflow runs on '${appliedBranch}' in this window.`
                        : 'No workflow runs in this window.'
                }
                nouns={['workflow', 'workflows']}
            />
            <div className="text-xs text-tertiary">
                Success rate and durations are computed over completed runs only — a run that hasn't settled is
                excluded, not counted as a failure. Window: {windowLabel}
                {appliedBranch ? ` · branch: ${appliedBranch}` : ''}.
            </div>
        </div>
    )
}
