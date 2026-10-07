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

export function warehouseSuggestionActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const statusChange = logItem.detail.changes?.find((change) => change.field === 'status')
    const verb = statusChange ? STATUS_VERBS[String(statusChange.after)] : undefined
    if (!verb) {
        return defaultDescriber(logItem, asNotification)
    }
    return {
        summary: activityLogSummary(logItem, verb, logItem.detail.name ?? 'suggestion'),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> {verb} the <b>{logItem.detail.name}</b>
            </>
        ),
    }
}
