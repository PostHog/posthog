import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

const scoutName = (logItem: ActivityLogItem): string =>
    logItem?.detail?.name || (logItem?.detail?.context as any)?.skill_name || 'scout'

export function signalScoutConfigActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const name = scoutName(logItem)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created scout{' '}
                    <strong>{name}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted scout{' '}
                    <strong>{name}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []
        const enabledChange = changes.find((change) => change.field === 'enabled')

        // Single-field enable/disable toggle gets a dedicated phrasing.
        if (enabledChange && changes.length === 1) {
            const verb = enabledChange.after ? 'enabled' : 'disabled'
            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> {verb} scout{' '}
                        <strong>{name}</strong>
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated scout{' '}
                    <strong>{name}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, name)
}
