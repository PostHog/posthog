import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { IssueListTitleColumn, IssueListTitleHeader } from 'products/error_tracking/frontend/components/TableColumns'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'

import { IssueCountCell, IssueVolumeCell } from './issueListCells'

// Title takes the remaining space; the sparkline + three counts get fixed tracks so
// every row lines up without any table chrome.
const ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_13rem_5rem_5rem_5rem] items-center gap-x-3'

const COLUMN_LABELS: { key: string; label: string }[] = [
    { key: 'volume', label: 'Volume' },
    { key: 'occurrences', label: 'Occurrences' },
    { key: 'sessions', label: 'Sessions' },
    { key: 'users', label: 'Users' },
]

/**
 * Table-less issues list. Renders each issue as a plain hover row (Linear-style) instead of the
 * DataTable, reusing the same title block and volume/count cells so individual issues look unchanged.
 * Expects an `issuesDataNodeLogic` provided by the surrounding scene.
 */
export function IssuesListRedesigned(): JSX.Element {
    const { results, responseLoading } = useValues(issuesDataNodeLogic)

    return (
        <div className="flex flex-col">
            <ListHeader results={results} />
            {responseLoading && results.length === 0 ? (
                <LoadingRows />
            ) : results.length === 0 ? (
                <EmptyState />
            ) : (
                results.map((record: ErrorTrackingIssue, index: number) => (
                    <IssueRow key={record.id} record={record} recordIndex={index} results={results} />
                ))
            )}
        </div>
    )
}

const ListHeader = ({ results }: { results: ErrorTrackingIssue[] }): JSX.Element => {
    return (
        <div className={cn(ROW_GRID, 'px-3 pb-2 text-xs font-medium text-muted')}>
            <IssueListTitleHeader results={results} />
            {COLUMN_LABELS.map(({ key, label }) => (
                <div key={key} className="text-center">
                    {label}
                </div>
            ))}
        </div>
    )
}

const IssueRow = ({
    record,
    recordIndex,
    results,
}: {
    record: ErrorTrackingIssue
    recordIndex: number
    results: ErrorTrackingIssue[]
}): JSX.Element => {
    return (
        <div
            data-attr="error-tracking-issue-row"
            className={cn(
                ROW_GRID,
                'px-3 py-1 border-b border-primary last:border-b-0 hover:bg-surface-secondary transition-colors'
            )}
        >
            <div className="min-w-0">
                <IssueListTitleColumn results={results} record={record} recordIndex={recordIndex} />
            </div>
            <IssueVolumeCell record={record} />
            <div className="text-center">
                <IssueCountCell record={record} columnName="occurrences" />
            </div>
            <div className="text-center">
                <IssueCountCell record={record} columnName="sessions" />
            </div>
            <div className="text-center">
                <IssueCountCell record={record} columnName="users" />
            </div>
        </div>
    )
}

const LoadingRows = (): JSX.Element => {
    return (
        <div className="flex flex-col">
            {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className={cn(ROW_GRID, 'px-3 py-3 border-b border-primary last:border-b-0')}>
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-4 w-1/3" />
                        <LemonSkeleton className="h-3 w-2/3" />
                    </div>
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-4 w-10 justify-self-center" />
                    <LemonSkeleton className="h-4 w-10 justify-self-center" />
                    <LemonSkeleton className="h-4 w-10 justify-self-center" />
                </div>
            ))}
        </div>
    )
}

const EmptyState = (): JSX.Element => {
    return (
        <div className="flex flex-col items-center justify-center gap-1 py-16 text-center">
            <span className="text-base font-semibold">No issues found</span>
            <span className="text-sm text-muted">
                Try changing the date range, changing the filters or removing the assignee.
            </span>
        </div>
    )
}
