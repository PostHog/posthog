import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
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

// Title takes the remaining space; the sparkline + three (roomier) count tracks line up every row
// without table chrome. The volume cell carries pr to open a gap before the count group.
const ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_13rem_6.5rem_6.5rem_6.5rem] items-center gap-x-3'
const VOLUME_GAP = 'pr-5'

/**
 * Table-less issues list. Renders each issue as a plain hover row (Linear-style) instead of the
 * DataTable: a fresh, compact title block (IssueRowRedesigned) plus the shared volume/count cells.
 * The `toolbar` is laid into the sticky header's title column so the metric column names align with
 * the rows below. Expects an `issuesDataNodeLogic` provided by the surrounding scene.
 */
export function IssuesListRedesigned({ toolbar }: { toolbar: ReactNode }): JSX.Element {
    const { results, responseLoading } = useValues(issuesDataNodeLogic)

    return (
        <>
            <ListHeader toolbar={toolbar} results={results} />
            {/* -mx-4 lets the rows and their dividers bleed to the scene edges (matching the sticky
                header), while px-4 on each row keeps the content aligned. */}
            <div className="-mx-4 flex flex-col">
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
        </>
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

/**
 * Sticky top bar. The toolbar sits in the title column and the metric column names sit in their own
 * (sortable) cells, so the header lines up with the rows and needs no separate divider beneath it.
 * When issues are selected the toolbar slot becomes the bulk-action bar.
 */
const ListHeader = ({ toolbar, results }: { toolbar: ReactNode; results: ErrorTrackingIssue[] }): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)

    return (
        <SceneStickyBar showBorderBottom={false} className="-mt-2">
            {/* Bottom-align so the metric column names sit just above the rows, not centered in the
                taller toolbar band. */}
            <div className={cn(ROW_GRID, 'items-end')}>
                <div className="min-w-0">
                    {selectedIssueIds.length > 0 ? (
                        <IssueActions issues={results} selectedIds={selectedIssueIds} />
                    ) : (
                        toolbar
                    )}
                </div>
                <div className={cn(VOLUME_GAP, 'text-center text-xs font-medium text-muted')}>Volume</div>
                <SortableCountHeader field="occurrences" label="Occurrences" />
                <SortableCountHeader field="sessions" label="Sessions" />
                <SortableCountHeader field="users" label="Users" />
            </div>
        </SceneStickyBar>
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
                'group/row border-b border-primary px-4 py-2 transition-colors last:border-b-0 hover:bg-surface-secondary'
            )}
        >
            <div className="min-w-0">
                <IssueRowRedesigned results={results} record={record} recordIndex={recordIndex} />
            </div>
            <div className={VOLUME_GAP}>
                <IssueVolumeCell record={record} />
            </div>
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
                <div key={index} className={cn(ROW_GRID, 'border-b border-primary px-4 py-3 last:border-b-0')}>
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-4 w-1/3" />
                        <LemonSkeleton className="h-3 w-2/3" />
                    </div>
                    <div className={VOLUME_GAP}>
                        <LemonSkeleton className="h-8 w-full" />
                    </div>
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
