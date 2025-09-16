import { useActions } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
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
    keyof ErrorTrackingIssue,
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
                    changed status of {nameAndLink(logItem)} from <strong>{before}</strong> to <strong>{after}</strong>
                </>,
            ],
        }
    },

    /** readonly / computed fields aren't described */
    id: () => null,
    name: () => null,
    description: () => null,
    aggregations: () => null,
    first_seen: () => null,
    last_seen: () => null,
    first_event: () => null,
    last_event: () => null,
    library: () => null,
    external_issues: () => null,
}

export function ActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ERROR_TRACKING_ISSUE) {
        console.error('describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'updated' || logItem.activity == 'assigned') {
        let changes: Description[] = []

        for (const change of logItem.detail.changes || []) {
            const field = change.field as keyof ErrorTrackingIssue

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
                    <SentenceList listParts={changes} prefix={<strong>{userNameForLogItem(logItem)}</strong>} />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, 'error tracking issue')
}
