import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

export function groupActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Group') {
        console.error('group describer received a non-group activity')
        return { description: null }
    }

    if (logItem.activity === 'update_property') {
        return {
            summary: activityLogSummary(
                logItem,
                `${logItem.detail?.changes?.[0]?.action || 'changed'} the property`,
                <code>{logItem.detail?.name}</code>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> {logItem.detail?.changes?.[0]?.action || 'changed'} the{' '}
                    <code>{logItem.detail?.name}</code> property.
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
