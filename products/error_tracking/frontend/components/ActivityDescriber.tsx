import { useActions } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from './Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from './Assignee/assigneeSelectLogic'

type ErrorTrackingIssueAssignee = Exclude<ErrorTrackingIssue['assignee'], null>

function AssigneeRenderer({ assignee }: { assignee: ErrorTrackingIssueAssignee }): JSX.Element {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <AssigneeResolver assignee={assignee}>
            {({ assignee }) => (
                <span className="flex gap-x-0.5">
                    <AssigneeIconDisplay assignee={assignee} />
                    <AssigneeLabelDisplay assignee={assignee} />
                </span>
            )}
        </AssigneeResolver>
    )
}

function relatedIssueIdsForLogItem(logItem: ActivityLogItem): string[] {
    const change = (logItem.detail.changes || []).find(
        (candidate) => candidate.field === 'merged_issue_ids' || candidate.field === 'split_issue_ids'
    )
    return Array.isArray(change?.after) ? change.after.map(String) : []
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    const name = logItem?.detail.name
    return logItem?.item_id ? (
        <Link to={urls.errorTrackingIssue(logItem.item_id)}>{name || 'an issue'}</Link>
    ) : name ? (
        <>{name}</>
    ) : (
        <i>an issue</i>
    )
}

const errorTrackingIssueActionsMapping: Record<
    keyof ErrorTrackingRelationalIssue,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: (change, logItem) => {
        const { before, after } = change || {}
        const unassignedBefore = before === null
        const unassignedAfter = after === null
        if (unassignedBefore && unassignedAfter) {
            return null
        }
        if (objectsEqual(before, after)) {
            return null
        }
        if (!before && !after) {
            return null
        }

        const wasAssigned = unassignedBefore && !unassignedAfter
        const wasUnassigned = !unassignedBefore && unassignedAfter

        return {
            description: [
                wasAssigned ? (
                    <>
                        assigned {nameAndLink(logItem)} to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                    </>
                ) : wasUnassigned ? (
                    <>
                        unassigned {nameAndLink(logItem)} from{' '}
                        <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} />
                    </>
                ) : (
                    <>
                        changed assignee from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} /> to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} /> on {nameAndLink(logItem)}
                    </>
                ),
            ],
        }
    },
    status: (change, logItem) => {
        const { before, after } = change || {}
        if (!before || !after) {
            return null
        }
        return {
            description: [
                <>
                    changed status of {nameAndLink(logItem)} from <strong>{String(before)}</strong> to{' '}
                    <strong>{String(after)}</strong>
                </>,
            ],
        }
    },

    /** readonly / computed fields aren't described */
    id: () => null,
    severity: () => null,
    name: () => null,
    description: () => null,
    first_seen: () => null,
    external_issues: () => null,
    cohort: () => null,
}

export function ActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ERROR_TRACKING_ISSUE) {
        console.error('describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'merged' || logItem.activity == 'split') {
        const relatedIssueIds = relatedIssueIdsForLogItem(logItem)
        const count = relatedIssueIds.length
        return {
            description: (
                <SentenceList
                    listParts={[
                        logItem.activity == 'merged' ? (
                            <>
                                merged {count === 1 ? 'an issue' : `${count} issues`} into {nameAndLink(logItem)}
                            </>
                        ) : (
                            <>
                                split {nameAndLink(logItem)} into{' '}
                                {count > 0 ? (
                                    <SentenceList
                                        listParts={relatedIssueIds.map((issueId, index) => (
                                            <Link key={issueId} to={urls.errorTrackingIssue(issueId)}>
                                                {count === 1 ? 'a new issue' : `new issue ${index + 1}`}
                                            </Link>
                                        ))}
                                    />
                                ) : (
                                    'new issues'
                                )}
                            </>
                        ),
                    ]}
                    prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                />
            ),
        }
    }

    if (logItem.activity == 'updated' || logItem.activity == 'assigned') {
        let changes: Description[] = []

        for (const change of logItem.detail.changes || []) {
            const field = change.field as keyof ErrorTrackingRelationalIssue

            if (!change?.field || !errorTrackingIssueActionsMapping[field]) {
                continue //  not all fields are describable
            }

            const actionHandler = errorTrackingIssueActionsMapping[field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue // unexpected log from backend is indescribable
            }

            const { description } = processedChange
            if (description) {
                changes = changes.concat(description)
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, 'error tracking issue')
}
