import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
} from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'products/error_tracking/frontend/components/Assignee/AssigneeSelect'
import { issueActionsLogic } from 'products/error_tracking/frontend/components/IssueActions/issueActionsLogic'
import {
    issueFiltersLogic,
    updateFilterSearchParams,
} from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { IssueStatusSelect } from 'products/error_tracking/frontend/components/IssueStatusSelect'
import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { errorTrackingIssueSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { sourceDisplay } from 'products/error_tracking/frontend/utils'

/** Resolve which issue IDs should be toggled, supporting shift-click range selection. */
function getShiftClickIds(
    results: { id: string }[],
    recordIndex: number,
    recordId: string,
    shiftKeyHeld: boolean,
    previouslyCheckedRecordIndex: number | null
): string[] {
    if (!shiftKeyHeld || previouslyCheckedRecordIndex === null) {
        return [recordId]
    }
    const start = Math.min(previouslyCheckedRecordIndex, recordIndex)
    const end = Math.max(previouslyCheckedRecordIndex, recordIndex) + 1
    return results.slice(start, end).map((r) => r.id)
}

const MetaDot = (): JSX.Element => <span className="text-quaternary select-none">·</span>

/**
 * Fresher take on the issue title block for the redesigned tab: runtime icon + name on the first
 * line, then the description, then the function/source location, then a quiet metadata line (status,
 * assignee, last seen) — keeping the original table's line-by-line distinction. The checkbox only
 * reveals on row hover (via the parent's `group/row`). Self-contained — duplicates the
 * selection/navigation wiring so the row can evolve independently of the table column.
 */
export const IssueRowRedesigned = ({
    record,
    recordIndex,
    results,
}: {
    record: ErrorTrackingIssue
    recordIndex: number
    results: ErrorTrackingIssue[]
}): JSX.Element => {
    const { selectedIssueIds, shiftKeyHeld, previouslyCheckedRecordIndex } = useValues(bulkSelectLogic)
    const { setSelectedIssueIds, setPreviouslyCheckedRecordIndex } = useActions(bulkSelectLogic)
    const { updateIssueAssignee, updateIssueStatus } = useActions(issueActionsLogic)
    const { dateRange, filterGroup, filterTestAccounts, searchQuery } = useValues(issueFiltersLogic)
    const { orderBy } = useValues(issueQueryOptionsLogic)

    const checked = selectedIssueIds.includes(record.id)
    const runtime = getRuntimeFromLib(record.library)

    const handleSelectionChange = (newValue: boolean): void => {
        const idsToToggle = getShiftClickIds(
            results,
            recordIndex,
            record.id,
            shiftKeyHeld,
            previouslyCheckedRecordIndex
        )
        setPreviouslyCheckedRecordIndex(recordIndex)
        setSelectedIssueIds(
            newValue
                ? [...new Set([...selectedIssueIds, ...idsToToggle])]
                : selectedIssueIds.filter((id) => !idsToToggle.includes(id))
        )
    }

    const issueUrl = useMemo(() => {
        const params: Params = {}
        updateFilterSearchParams(params, { dateRange, filterGroup, filterTestAccounts, searchQuery })
        return urls.errorTrackingIssue(record.id, { timestamp: record.last_seen, ...params })
    }, [dateRange, filterGroup, filterTestAccounts, searchQuery, record.last_seen, record.id])

    return (
        <div className="flex min-w-0 items-start gap-2">
            <LemonCheckbox
                checked={checked}
                onChange={handleSelectionChange}
                className={cn(
                    'mt-0.5 shrink-0 transition-opacity',
                    checked ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100'
                )}
            />
            <div className="flex min-w-0 flex-col gap-0.5">
                <Link
                    to={issueUrl}
                    className="group/title flex min-w-0 items-center gap-2"
                    onClick={() => {
                        const issueLogic = errorTrackingIssueSceneLogic({ id: record.id, timestamp: record.last_seen })
                        issueLogic.mount()
                        issueLogic.actions.setIssue(record)
                    }}
                >
                    <RuntimeIcon className="shrink-0 text-secondary" runtime={runtime} fontSize="0.8rem" />
                    <span className="truncate text-[0.9rem] font-semibold text-default group-hover/title:text-accent">
                        {record.name || 'Unknown Type'}
                    </span>
                </Link>
                {record.description && <div className="truncate text-[0.82rem] text-muted">{record.description}</div>}
                {(record.function || record.source) && (
                    <div className="truncate text-[0.8rem] font-light italic text-muted">
                        {record.function}
                        {record.source ? <> in {sourceDisplay(record.source)}</> : null}
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted">
                    <IssueStatusSelect
                        status={record.status}
                        onChange={(status) => updateIssueStatus(record.id, status)}
                    />
                    <MetaDot />
                    <AssigneeSelect
                        assignee={record.assignee}
                        onChange={(assignee) => updateIssueAssignee(record.id, assignee)}
                    >
                        {(anyAssignee) => (
                            <div
                                className="flex cursor-pointer items-center gap-1 rounded p-0.5 hover:bg-fill-button-tertiary-hover"
                                role="button"
                            >
                                <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                                <AssigneeLabelDisplay
                                    assignee={anyAssignee}
                                    className="text-xs text-muted"
                                    size="xsmall"
                                />
                            </div>
                        )}
                    </AssigneeSelect>
                    <MetaDot />
                    {orderBy === 'first_seen' && record.first_seen ? (
                        <>
                            <TZLabel time={record.first_seen} className="text-xs" suffix="old" delayMs={750} />
                            <MetaDot />
                        </>
                    ) : null}
                    {record.last_seen ? <TZLabel time={record.last_seen} className="text-xs" delayMs={750} /> : null}
                </div>
            </div>
        </div>
    )
}
