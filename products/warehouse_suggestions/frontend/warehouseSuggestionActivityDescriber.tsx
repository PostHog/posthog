import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

const STATUS_VERBS: Record<string, string> = {
    accepted: 'accepted',
    dismissed: 'dismissed',
    proposed: 'reopened',
    expired: 'expired',
    auto_resolved: 'resolved',
}

function statusVerb(logItem: ActivityLogItem): string | undefined {
    const statusChange = logItem.detail.changes?.find((change) => change.field === 'status')
    return statusChange ? STATUS_VERBS[String(statusChange.after)] : undefined
}

function assigneeVerb(logItem: ActivityLogItem): string | undefined {
    const assigneeChange = logItem.detail.changes?.find((change) => change.field === 'assignee')
    if (!assigneeChange) {
        return undefined
    }
    return assigneeChange.after ? 'assigned' : 'unassigned'
}

export function warehouseSuggestionActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const verb = statusVerb(logItem) ?? assigneeVerb(logItem)
    if (!verb) {
        return defaultDescriber(logItem, asNotification)
    }
    const name = logItem.detail.name ?? 'suggestion'
    return {
        summary: activityLogSummary(logItem, verb, name),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> {verb} the <b>{name}</b>
            </>
        ),
    }
}
