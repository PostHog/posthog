import { useActions } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { describeMappedChanges } from 'lib/components/ActivityLog/activityDescriptions/describeMappedChanges'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { TZLabel } from 'lib/components/TZLabel'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from './Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from './Assignee/assigneeSelectLogic'

// Pinned: the trigger job type of the activity entry that ingestion writes when it reopens an issue.
// It must match INGESTION_REOPEN_TRIGGER_JOB_TYPE in the backend.
const INGESTION_REOPEN_JOB_TYPE = 'error_tracking_ingestion'
// Pinned: the resolved_until value the backend logs for an issue resolved in the next release.
const RESOLVED_UNTIL_NEW_RELEASE = 'new_release'

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

function hasChangedField(logItem: ActivityLogItem | undefined, field: string): boolean {
    return (logItem?.detail.changes ?? []).some((change) => change.field === field)
}

function resolvedInNextRelease(logItem?: ActivityLogItem): boolean {
    return (logItem?.detail.changes ?? []).some(
        (change) => change.field === 'resolved_until' && change.after === RESOLVED_UNTIL_NEW_RELEASE
    )
}

function reopenedByReleaseVersion(logItem?: ActivityLogItem): string | null {
    const version = logItem?.detail.trigger?.payload?.release?.version
    return typeof version === 'string' && version ? version : null
}

function reopeningExceptionTime(logItem?: ActivityLogItem): JSX.Element | null {
    const timestamp = logItem?.detail.trigger?.payload?.exception_timestamp
    return typeof timestamp === 'string' && timestamp ? (
        <>
            {' '}
            on <TZLabel time={timestamp} timestampStyle="absolute" />
        </>
    ) : null
}

function describeIngestionReopen(logItem?: ActivityLogItem): ChangeMapping {
    const version = reopenedByReleaseVersion(logItem)
    if (version) {
        return {
            summary: [<>Reopened by release {version}</>],
            description: [
                <>
                    reopened {nameAndLink(logItem)} after an exception from release <strong>{version}</strong>
                    {reopeningExceptionTime(logItem)}
                </>,
            ],
        }
    }
    return {
        summary: ['Reopened by a new exception'],
        description: [
            <>
                reopened {nameAndLink(logItem)} after a new exception{reopeningExceptionTime(logItem)}
            </>,
        ],
    }
}

const errorTrackingIssueActionsMapping: Record<
    keyof ErrorTrackingRelationalIssue | 'resolved_until',
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: (change, logItem) => {
        const { before, after } = change || {}
        const unassignedBefore = before === null
        const unassignedAfter = after === null
        if (objectsEqual(before, after)) {
            return null
        }
        if (!before && !after) {
            return null
        }

        const wasAssigned = unassignedBefore && !unassignedAfter
        const wasUnassigned = !unassignedBefore && unassignedAfter

        if (wasAssigned) {
            return {
                summary: [
                    <>
                        Assigned to <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                    </>,
                ],
                description: [
                    <>
                        assigned {nameAndLink(logItem)} to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                    </>,
                ],
            }
        }
        if (wasUnassigned) {
            return {
                summary: [
                    <>
                        Unassigned from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} />
                    </>,
                ],
                description: [
                    <>
                        unassigned {nameAndLink(logItem)} from{' '}
                        <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} />
                    </>,
                ],
            }
        }
        return {
            summary: [
                <>
                    Changed assignee from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} /> to{' '}
                    <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                </>,
            ],
            description: [
                <>
                    changed assignee from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} /> to{' '}
                    <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} /> on {nameAndLink(logItem)}
                </>,
            ],
        }
    },
    status: (change, logItem) => {
        const { before, after } = change || {}
        if (!before || !after) {
            return null
        }
        if (logItem?.detail.trigger?.job_type === INGESTION_REOPEN_JOB_TYPE) {
            return describeIngestionReopen(logItem)
        }
        if (after === 'resolved' && resolvedInNextRelease(logItem)) {
            return {
                summary: ['Resolved in the next release'],
                description: [<>resolved {nameAndLink(logItem)} in the next release</>],
            }
        }
        return {
            summary: [
                <>
                    Changed status from {String(before)} to {String(after)}
                </>,
            ],
            description: [
                <>
                    changed status of {nameAndLink(logItem)} from <strong>{String(before)}</strong> to{' '}
                    <strong>{String(after)}</strong>
                </>,
            ],
        }
    },

    resolved_until: (change, logItem) => {
        // The status change of the same entry describes the mode together with the resolve.
        if (!change?.after || hasChangedField(logItem, 'status')) {
            return null
        }
        return change.after === RESOLVED_UNTIL_NEW_RELEASE
            ? {
                  summary: ['Changed to reopen only in a newer release'],
                  description: [<>changed {nameAndLink(logItem)} to reopen only in a newer release</>],
              }
            : {
                  summary: ['Changed to reopen the next time it happens'],
                  description: [<>changed {nameAndLink(logItem)} to reopen the next time it happens</>],
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
    tags: () => null,
}

function describeIssueMergeOrSplit(logItem: ActivityLogItem): HumanizedChange {
    const relatedIssueIds = relatedIssueIdsForLogItem(logItem)
    const count = relatedIssueIds.length
    return {
        summary: activityLogSummary(
            logItem,
            logItem.activity === 'merged' ? (
                <>Merged {count === 1 ? 'an issue' : `${count} issues`} into this issue</>
            ) : (
                <>
                    Split into{' '}
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
            nameAndLink(logItem)
        ),
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
                prefix={<ActivityLogUserName logItem={logItem} />}
            />
        ),
    }
}

export function ActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ERROR_TRACKING_ISSUE) {
        console.error('describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'merged' || logItem.activity == 'split') {
        return describeIssueMergeOrSplit(logItem)
    }

    if (logItem.activity == 'updated' || logItem.activity == 'assigned') {
        const changes = describeMappedChanges(logItem, errorTrackingIssueActionsMapping, nameAndLink(logItem), null)
        if (changes) {
            return changes
        }
    }

    return defaultDescriber(logItem, asNotification, 'error tracking issue')
}
