import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
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
 * Fresher take on the issue title block for the redesigned tab: a single prominent line
 * (icon + name + inline description) over a quiet metadata line (status, assignee, last seen,
 * source). Self-contained — duplicates the selection/navigation wiring on purpose so the row can
 * evolve independently of the shared table column.
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
        <div className="flex min-w-0 items-start gap-2.5">
            <LemonCheckbox checked={checked} onChange={handleSelectionChange} className="mt-[3px] shrink-0" />
            <div className="flex min-w-0 flex-col gap-0.5">
                <Link
                    to={issueUrl}
                    className="group/title flex min-w-0 items-baseline gap-2"
                    onClick={() => {
                        const issueLogic = errorTrackingIssueSceneLogic({ id: record.id, timestamp: record.last_seen })
                        issueLogic.mount()
                        issueLogic.actions.setIssue(record)
                    }}
                >
                    <RuntimeIcon className="shrink-0 self-center text-secondary" runtime={runtime} fontSize="0.8rem" />
                    <span className="truncate text-[0.9rem] font-semibold text-default group-hover/title:text-accent">
                        {record.name || 'Unknown Type'}
                    </span>
                    {record.description && (
                        <span className="hidden min-w-0 truncate text-[0.8rem] text-muted md:inline">
                            {record.description}
                        </span>
                    )}
                </Link>
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
                    {record.function ? (
                        <>
                            <MetaDot />
                            <span className="min-w-0 truncate italic">
                                {record.function}
                                {record.source ? ` in ${sourceDisplay(record.source)}` : ''}
                            </span>
                        </>
                    ) : null}
                </div>
            </div>
        </div>
    )
}
