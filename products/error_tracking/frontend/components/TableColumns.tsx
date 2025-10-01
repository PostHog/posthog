import { useActions, useValues } from 'kea'

import { IconChevronDown, IconMinus } from '@posthog/icons'
import { LemonCheckbox, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ErrorTrackingCorrelatedIssue, ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { bulkSelectLogic } from '../logics/bulkSelectLogic'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './Assignee/AssigneeDisplay'
import { AssigneeSelect } from './Assignee/AssigneeSelect'
import { issueActionsLogic } from './IssueActions/issueActionsLogic'
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
        <div className="flex gap-2 items-center">
            <LemonCheckbox
                checked={allSelected}
                onChange={() => (allSelected ? setSelectedIssueIds([]) : setSelectedIssueIds(results.map((r) => r.id)))}
            />
            <span>Issue</span>
        </div>
    )
}

export const IssueListTitleColumn = <T extends ErrorTrackingIssue | ErrorTrackingCorrelatedIssue>(props: {
    results: T[]
    record: unknown
    recordIndex: number
}): JSX.Element => {
    const { selectedIssueIds, shiftKeyHeld, previouslyCheckedRecordIndex } = useValues(bulkSelectLogic)
    const { setSelectedIssueIds, setPreviouslyCheckedRecordIndex } = useActions(bulkSelectLogic)
    const { updateIssueAssignee, updateIssueStatus } = useActions(issueActionsLogic)

    const record = props.record as ErrorTrackingIssue
    const checked = selectedIssueIds.includes(record.id)
    const runtime = getRuntimeFromLib(record.library)
    const recordIndex = props.recordIndex

    const onChange = (newValue: boolean): void => {
        const includedIds: string[] = []

        if (!shiftKeyHeld || previouslyCheckedRecordIndex === null) {
            includedIds.push(record.id)
        } else {
            const start = Math.min(previouslyCheckedRecordIndex, recordIndex)
            const end = Math.max(previouslyCheckedRecordIndex, recordIndex) + 1
            includedIds.push(...props.results.slice(start, end).map((r) => r.id))
        }

        setPreviouslyCheckedRecordIndex(recordIndex)
        setSelectedIssueIds(
            newValue
                ? [...new Set([...selectedIssueIds, ...includedIds])]
                : selectedIssueIds.filter((id) => !includedIds.includes(id))
        )
    }

    return (
        <div className="flex items-start gap-x-2 group my-1">
            <LemonCheckbox className="h-[1rem]" checked={checked} onChange={onChange} />

            <div className="flex flex-col gap-[3px]">
                <Link
                    className="flex-1 pr-12"
                    to={urls.errorTrackingIssue(record.id, { timestamp: record.last_seen })}
                    onClick={() => {
                        const issueLogic = errorTrackingIssueSceneLogic({ id: record.id, timestamp: record.last_seen })
                        issueLogic.mount()
                        issueLogic.actions.setIssue(record)
                    }}
                >
                    <div className="flex items-center h-[1rem] gap-2">
                        <RuntimeIcon className="shrink-0" runtime={runtime} fontSize="0.7rem" />
                        <span className="font-semibold text-[0.9rem] line-clamp-1">
                            {record.name || 'Unknown Type'}
                        </span>
                    </div>
                </Link>
                <div title={record.description || undefined} className="font-medium line-clamp-1 text-[var(--gray-8)]">
                    {record.description}
                </div>
                <div className="flex items-center text-secondary">
                    <IssueStatusSelect
                        status={record.status}
                        onChange={(status) => updateIssueStatus(record.id, status)}
                    />
                    <CustomGroupSeparator />
                    <AssigneeSelect
                        assignee={record.assignee}
                        onChange={(assignee) => updateIssueAssignee(record.id, assignee)}
                    >
                        {(anyAssignee) => (
                            <div
                                className="flex items-center hover:bg-fill-button-tertiary-hover p-[0.1rem] rounded cursor-pointer"
                                role="button"
                            >
                                <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                                <AssigneeLabelDisplay
                                    assignee={anyAssignee}
                                    className="ml-1 text-xs text-secondary"
                                    size="xsmall"
                                />
                                <IconChevronDown />
                            </div>
                        )}
                    </AssigneeSelect>
                    <CustomGroupSeparator />
                    <TZLabel time={record.first_seen} className="border-dotted border-b text-xs ml-1" delayMs={750} />
                    <IconChevronRight className="text-quaternary mx-1" />
                    {record.last_seen ? (
                        <TZLabel time={record.last_seen} className="border-dotted border-b text-xs" delayMs={750} />
                    ) : (
                        <LemonSkeleton />
                    )}
                </div>
            </div>
        </div>
    )
}

const CustomGroupSeparator = (): JSX.Element => <IconMinus className="text-quaternary rotate-90" />
