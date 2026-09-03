import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconMinus } from '@posthog/icons'
import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { Button, ButtonGroup, SelectTriggerIcon } from 'lib/ui/quill'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingCorrelatedIssue, ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { bulkSelectLogic } from '../logics/bulkSelectLogic'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { sourceDisplay } from '../utils'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './Assignee/AssigneeDisplay'
import { QuillAssigneeSelect } from './Assignee/QuillAssigneeSelect'
import { issueActionsLogic } from './IssueActions/issueActionsLogic'
import { issueFiltersLogic, updateFilterSearchParams } from './IssueFilters/issueFiltersLogic'
import { IssueSeveritySelect } from './IssueSeveritySelect'
import { IssueStatusSelect } from './IssueStatusSelect'
import { RuntimeIcon } from './RuntimeIcon'

export const IssueListTitleHeader = ({
    results,
}: {
    results: (ErrorTrackingIssue | ErrorTrackingCorrelatedIssue)[]
}): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { setSelectedIssueIds } = useActions(bulkSelectLogic)
    const allSelected = results.length == selectedIssueIds.length && selectedIssueIds.length > 0

    return (
        <div className="flex gap-3 items-center -ml-1">
            <LemonCheckbox
                checked={allSelected}
                onChange={() => (allSelected ? setSelectedIssueIds([]) : setSelectedIssueIds(results.map((r) => r.id)))}
            />
            <span>Issue</span>
        </div>
    )
}

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

export const IssueListTitleColumn = (props: {
    results: (ErrorTrackingIssue | ErrorTrackingCorrelatedIssue)[]
    record: unknown
    recordIndex: number
}): JSX.Element => {
    const record = props.record as ErrorTrackingIssue
    const { recordIndex, results } = props
    const { selectedIssueIds, shiftKeyHeld, previouslyCheckedRecordIndex } = useValues(bulkSelectLogic)
    const { setSelectedIssueIds, setPreviouslyCheckedRecordIndex } = useActions(bulkSelectLogic)
    const { updateIssueAssignee, updateIssueSeverity, updateIssueStatus } = useActions(issueActionsLogic)
    const { severityUpdateInFlightIds } = useValues(issueActionsLogic)
    const { dateRange, filterGroup, filterTestAccounts, searchQuery } = useValues(issueFiltersLogic)
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

    // Keep params in sync between listing and details views
    const issueUrl = useMemo(() => {
        const params: Params = {}
        updateFilterSearchParams(params, {
            dateRange,
            filterGroup,
            filterTestAccounts,
            searchQuery,
        })
        return urls.errorTrackingIssue(record.id, {
            timestamp: record.last_seen,
            ...params,
        })
    }, [dateRange, filterGroup, filterTestAccounts, searchQuery, record.last_seen, record.id])

    return (
        <div className="flex items-start gap-x-2 group my-1 [--line-height:1.3rem] -ml-2">
            <LemonCheckbox className="h-(--line-height) mx-1" checked={checked} onChange={handleSelectionChange} />
            <div className="flex flex-col gap-[2px]">
                <IssueTitle record={record} issueUrl={issueUrl} runtime={runtime} />
                <div
                    title={record.description || undefined}
                    className="font-medium line-clamp-1 text-[var(--gray-8)] h-(--line-height)"
                >
                    {record.description}
                </div>
                {(record.function || record.source) && (
                    <div className="line-clamp-1 text-[var(--gray-6)] italic font-light h-(--line-height)">
                        {record.function}
                        {record.source ? <> in {sourceDisplay(record.source)}</> : <></>}
                    </div>
                )}
                <IssueMetadata
                    record={record}
                    severityLoading={severityUpdateInFlightIds.includes(record.id)}
                    onStatusChange={(status) => updateIssueStatus(record.id, status)}
                    onSeverityChange={(severity) => updateIssueSeverity(record.id, severity)}
                    onAssigneeChange={(assignee) => updateIssueAssignee(record.id, assignee)}
                />
            </div>
        </div>
    )
}

const IssueTitle = ({
    record,
    issueUrl,
    runtime,
}: {
    record: ErrorTrackingIssue
    issueUrl: string
    runtime: ErrorTrackingRuntime
}): JSX.Element => (
    <Link
        className="flex-1 pr-12 text-[0.9rem]"
        to={issueUrl}
        onClick={() => {
            const issueLogic = errorTrackingIssueSceneLogic({
                id: record.id,
                timestamp: record.last_seen,
            })
            issueLogic.mount()
            issueLogic.actions.setIssue(record)
        }}
    >
        <div className="flex items-center gap-2 h-(--line-height)">
            <RuntimeIcon className="shrink-0" runtime={runtime} fontSize="0.7rem" />
            <span className="font-semibold line-clamp-1">{record.name || 'Unknown Type'}</span>
        </div>
    </Link>
)

const IssueMetadata = ({
    record,
    severityLoading,
    onStatusChange,
    onSeverityChange,
    onAssigneeChange,
}: {
    record: ErrorTrackingIssue
    severityLoading: boolean
    onStatusChange: (status: ErrorTrackingIssue['status']) => void
    onSeverityChange: (severity: NonNullable<ErrorTrackingIssue['severity']> | null) => void
    onAssigneeChange: (assignee: ErrorTrackingIssue['assignee']) => void
}): JSX.Element => (
    <div className="my-1 flex h-6 items-center text-secondary">
        <ButtonGroup>
            <IssueStatusSelect status={record.status} onChange={onStatusChange} />
            <IssueSeveritySelect severity={record.severity} onChange={onSeverityChange} loading={severityLoading} />
            <QuillAssigneeSelect assignee={record.assignee} onChange={onAssigneeChange}>
                {(anyAssignee) => (
                    <Button variant="outline" size="sm">
                        <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                        <AssigneeLabelDisplay assignee={anyAssignee} className="text-xs text-secondary" size="xsmall" />
                        <SelectTriggerIcon />
                    </Button>
                )}
            </QuillAssigneeSelect>
        </ButtonGroup>
    </div>
)

export const CustomSeparator = (): JSX.Element => <IconMinus className="text-quaternary rotate-90" />
