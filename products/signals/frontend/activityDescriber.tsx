import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

const scoutName = (logItem: ActivityLogItem): string =>
    logItem?.detail?.name || (logItem?.detail?.context as any)?.skill_name || 'scout'

// Descriptions are plain strings (no JSX): the signals product package doesn't declare
// `react`, so a `.tsx` file using JSX can't resolve `react/jsx-runtime`. `Description`
// accepts `string`, which keeps this describer dependency-free.
export function signalScoutConfigActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const name = scoutName(logItem)
    const user = userNameForLogItem(logItem)

    if (logItem.activity === 'created') {
        return { description: `${user} created scout ${name}` }
    }

    if (logItem.activity === 'deleted') {
        return { description: `${user} deleted scout ${name}` }
    }

    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []
        const enabledChange = changes.find((change) => change.field === 'enabled')

        // Single-field enable/disable toggle gets a dedicated phrasing.
        if (enabledChange && changes.length === 1) {
            const verb = enabledChange.after ? 'enabled' : 'disabled'
            return { description: `${user} ${verb} scout ${name}` }
        }

        return { description: `${user} updated scout ${name}` }
    }

    return defaultDescriber(logItem, asNotification, name)
}
