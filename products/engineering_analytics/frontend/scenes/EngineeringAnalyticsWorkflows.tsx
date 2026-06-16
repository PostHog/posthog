import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { githubWorkflowUrl } from '../lib/github'
import { WorkflowHealthRow, engineeringAnalyticsLogic, workflowTrendSeries } from './engineeringAnalyticsLogic'

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

export function EngineeringAnalyticsWorkflows(): JSX.Element {
    const { workflowHealth, workflowHealthLoading, loadFailed, workflowDateFrom, workflowDateTo } =
        useValues(engineeringAnalyticsLogic)
    const { setWorkflowDateRange } = useActions(engineeringAnalyticsLogic)

    if (loadFailed) {
        return <ConnectGitHubSource />
    }

    const windowLabel = dateFilterToText(workflowDateFrom, workflowDateTo, 'Last 30 days') ?? 'Last 30 days'

    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
            render: (_, row) => (
                <Link
                    to={githubWorkflowUrl(row.repoOwner, row.repoName, row.workflowName)}
                    target="_blank"
                    className="font-medium"
                >
                    {row.workflowName}
                </Link>
            ),
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
            title: 'Trend',
            key: 'trend',
            // Pinned so the layout doesn't shift when sorting reorders rows with and without history.
            width: 272,
            render: function RenderTrend(_, row) {
                if (row.daily.length === 0) {
                    return <span className="text-xs text-secondary">—</span>
                }
                const { values, labels } = workflowTrendSeries(row.daily)
                return (
                    <Sparkline
                        className="h-8"
                        type="bar"
                        name="Non-passing"
                        data={values}
                        labels={labels}
                        maximumIndicator={false}
                        renderTooltipValue={(value) => `${humanFriendlyNumber(value * 100)}%`}
                    />
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
            </div>
            <LemonTable
                data-attr="engineering-analytics-workflow-table"
                size="small"
                columns={columns}
                dataSource={workflowHealth}
                rowKey={(row) => `${row.repoOwner}/${row.repoName}:${row.workflowName}`}
                loading={workflowHealthLoading}
                useURLForSorting={false}
                pagination={{ pageSize: 50 }}
                emptyState="No workflow runs in this window."
                nouns={['workflow', 'workflows']}
            />
            <div className="text-xs text-tertiary">
                Success rate and durations are computed over completed runs only — a run that hasn't settled is
                excluded, not counted as a failure. Window: {windowLabel}.
            </div>
        </div>
    )
}
