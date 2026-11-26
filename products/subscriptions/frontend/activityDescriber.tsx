import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

function ownerEmail(owner: ActivityChange['after'], fallback: string): string {
    return owner && typeof owner === 'object' && !Array.isArray(owner) && typeof owner.email === 'string'
        ? owner.email
        : fallback
}

export function subscriptionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (!['took_ownership', 'transferred_ownership'].includes(logItem.activity)) {
        return defaultDescriber(logItem, asNotification)
    }

    const isTransfer = logItem.activity === 'transferred_ownership'
    const change = logItem.detail.changes?.find((change) => change.field === 'created_by')
    const action = isTransfer ? 'transferred ownership of' : 'took ownership of'
    const resource = (
        <>
            <strong>{logItem.detail.name || 'the subscription'}</strong>
            {isTransfer && (
                <>
                    {' '}
                    from <strong>{ownerEmail(change?.before, 'the previous owner')}</strong> to{' '}
                    <strong>{ownerEmail(change?.after, 'the new owner')}</strong>
                </>
            )}
        </>
    )
    return {
        summary: activityLogSummary(logItem, action, resource),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> {action} {resource}
            </>
        ),
    }
}
