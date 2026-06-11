import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { WorkflowHealthRow, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

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
    const { workflowHealth, workflowHealthLoading, loadFailed } = useValues(engineeringAnalyticsLogic)

    if (loadFailed) {
        return <ConnectGitHubSource />
    }

    const columns: LemonTableColumns<WorkflowHealthRow> = [
        {
            title: 'Workflow',
            key: 'workflowName',
            render: (_, row) => <span className="font-medium">{row.workflowName}</span>,
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
            <LemonTable
                data-attr="engineering-analytics-workflow-table"
                size="small"
                columns={columns}
                dataSource={workflowHealth}
                rowKey="workflowName"
                loading={workflowHealthLoading}
                useURLForSorting={false}
                pagination={{ pageSize: 50 }}
                emptyState="No workflow runs in the last 30 days."
                nouns={['workflow', 'workflows']}
            />
            <div className="text-xs text-tertiary">
                Success rate and durations are computed over completed runs only — a run that hasn't settled is
                excluded, not counted as a failure. Window: last 30 days.
            </div>
        </div>
    )
}
