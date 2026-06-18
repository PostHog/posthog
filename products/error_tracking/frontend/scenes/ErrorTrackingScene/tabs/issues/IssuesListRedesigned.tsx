import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonCheckbox, LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { IssueActions } from 'products/error_tracking/frontend/components/IssueActions/IssueActions'
import {
    ErrorTrackingQueryOrderBy,
    ErrorTrackingQueryOrderDirection,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'

import { IssueCountCell, IssueVolumeCell } from './issueListCells'
import { IssueRowRedesigned } from './IssueRowRedesigned'

// Title takes the remaining space; the sparkline + three counts get fixed tracks so
// every row lines up without any table chrome.
const ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_13rem_5rem_5rem_5rem] items-center gap-x-3'

/**
 * Table-less issues list. Renders each issue as a plain hover row (Linear-style) instead of the
 * DataTable: a fresh, compact title block (IssueRowRedesigned) plus the shared volume/count cells.
 * Expects an `issuesDataNodeLogic` provided by the surrounding scene.
 */
export function IssuesListRedesigned(): JSX.Element {
    const { results, responseLoading } = useValues(issuesDataNodeLogic)

    return (
        <div className="flex flex-col">
            <ColumnHeaders results={results} />
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

const SortArrow = ({ direction }: { direction: ErrorTrackingQueryOrderDirection }): JSX.Element => (
    <IconArrowRight className={cn('text-xs', direction === 'DESC' ? 'rotate-90' : '-rotate-90')} />
)

/** Count column header that sorts by its field, toggling direction when already active. */
const SortableCountHeader = ({ field, label }: { field: ErrorTrackingQueryOrderBy; label: string }): JSX.Element => {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)
    const active = orderBy === field

    return (
        <button
            type="button"
            onClick={() => (active ? setOrderDirection(orderDirection === 'DESC' ? 'ASC' : 'DESC') : setOrderBy(field))}
            className={cn(
                'flex w-full items-center justify-center gap-1 rounded px-1 py-0.5 text-xs font-medium transition-colors hover:bg-fill-button-tertiary-hover',
                active ? 'text-default' : 'text-muted hover:text-default'
            )}
        >
            <span>{label}</span>
            {active && <SortArrow direction={orderDirection} />}
        </button>
    )
}

const ColumnHeaders = ({ results }: { results: ErrorTrackingIssue[] }): JSX.Element => {
    return (
        <div className={cn(ROW_GRID, 'border-b border-primary px-2 pb-2 pt-1')}>
            <SelectAllHeader results={results} />
            <div className="text-center text-xs font-medium text-muted">Volume</div>
            <SortableCountHeader field="occurrences" label="Occurrences" />
            <SortableCountHeader field="sessions" label="Sessions" />
            <SortableCountHeader field="users" label="Users" />
        </div>
    )
}

/**
 * Self-contained select-all + bulk action header. Doesn't go through the shared table header so the
 * bulk actions always render inline here, independent of the v1/v2 search bar variant.
 */
const SelectAllHeader = ({ results }: { results: ErrorTrackingIssue[] }): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { setSelectedIssueIds } = useActions(bulkSelectLogic)
    const allSelected = results.length === selectedIssueIds.length && selectedIssueIds.length > 0

    return (
        <div className="-ml-1 flex items-center gap-3">
            <LemonCheckbox
                checked={allSelected}
                onChange={() => (allSelected ? setSelectedIssueIds([]) : setSelectedIssueIds(results.map((r) => r.id)))}
            />
            {selectedIssueIds.length > 0 ? (
                <IssueActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <span className="text-xs font-medium text-muted">Issue</span>
            )}
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
                'border-b border-primary px-2 py-2 transition-colors last:border-b-0 hover:bg-surface-secondary'
            )}
        >
            <div className="min-w-0">
                <IssueRowRedesigned results={results} record={record} recordIndex={recordIndex} />
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
                <div key={index} className={cn(ROW_GRID, 'border-b border-primary px-2 py-3 last:border-b-0')}>
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
