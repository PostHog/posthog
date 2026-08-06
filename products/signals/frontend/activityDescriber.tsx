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

// Stored as "<channel_id>|#channel-name"; only the readable half is worth showing.
const channelLabel = (value: unknown): string => {
    const raw = typeof value === 'string' ? value : ''
    const name = raw.split('|')[1] || raw
    return name || 'a channel'
}

export function signalTeamConfigActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const user = userNameForLogItem(logItem)

    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []

        // Each setting has its own control in the inbox, so a single-field edit is the common case
        // and the one worth spelling out.
        if (changes.length === 1) {
            const change = changes[0]

            if (change.field === 'autostart_enabled') {
                // Only an explicit false is an opt-out; never having set it leaves PR generation on.
                const verb = change.after === false ? 'turned off' : 'turned on'
                return { description: `${user} ${verb} PR generation for inbox reports` }
            }

            if (change.field === 'default_autostart_priority') {
                return {
                    description: `${user} changed the PR generation threshold from ${change.before} to ${change.after}`,
                }
            }

            if (change.field === 'default_slack_notification_channel') {
                return {
                    description: change.after
                        ? `${user} set the default Slack channel for inbox notifications to ${channelLabel(change.after)}`
                        : `${user} cleared the default Slack channel for inbox notifications`,
                }
            }

            if (change.field === 'autostart_base_branches') {
                return { description: `${user} changed the base branches inbox PRs target` }
            }
        }

        return { description: `${user} updated the team's inbox settings` }
    }

    return defaultDescriber(logItem, asNotification, 'inbox settings')
}
