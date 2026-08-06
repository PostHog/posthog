import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    describeUserAction,
} from 'lib/components/ActivityLog/humanizeActivity'

const scoutName = (logItem: ActivityLogItem): string =>
    logItem?.detail?.name || (logItem?.detail?.context as any)?.skill_name || 'scout'

// These describers pass the sentence after the actor's name to `describeUserAction` rather than
// building their own JSX: the signals product package doesn't declare `react`, so a `.tsx` file
// using JSX can't resolve `react/jsx-runtime`. The helper also masks the actor's name, which can
// be an email address, from autocapture and session replay.
export function signalScoutConfigActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const name = scoutName(logItem)

    if (logItem.activity === 'created') {
        return describeUserAction(logItem, `created scout ${name}`)
    }

    if (logItem.activity === 'deleted') {
        return describeUserAction(logItem, `deleted scout ${name}`)
    }

    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []
        const enabledChange = changes.find((change) => change.field === 'enabled')

        // Single-field enable/disable toggle gets a dedicated phrasing.
        if (enabledChange && changes.length === 1) {
            const verb = enabledChange.after ? 'enabled' : 'disabled'
            return describeUserAction(logItem, `${verb} scout ${name}`)
        }

        return describeUserAction(logItem, `updated scout ${name}`)
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
    if (logItem.activity === 'updated') {
        const changes = logItem.detail?.changes ?? []

        // Each setting has its own control in the inbox, so a single-field edit is the common case
        // and the one worth spelling out.
        if (changes.length === 1) {
            const change = changes[0]

            if (change.field === 'autostart_enabled') {
                // Null means the team never set the switch, which leaves PR generation on, so only
                // an explicit false is an opt-out. A null/true swap moves the stored value without
                // moving the setting, so it falls through to the generic line rather than claiming
                // PR generation was turned on or off.
                const wasOn = change.before !== false
                const isOn = change.after !== false
                if (wasOn !== isOn) {
                    return describeUserAction(logItem, `turned ${isOn ? 'on' : 'off'} PR generation for inbox reports`)
                }
            }

            if (change.field === 'default_autostart_priority') {
                return describeUserAction(
                    logItem,
                    `changed the PR generation threshold from ${change.before} to ${change.after}`
                )
            }

            if (change.field === 'default_slack_notification_channel') {
                return describeUserAction(
                    logItem,
                    change.after
                        ? `set the default Slack channel for inbox notifications to ${channelLabel(change.after)}`
                        : 'cleared the default Slack channel for inbox notifications'
                )
            }

            if (change.field === 'autostart_base_branches') {
                return describeUserAction(logItem, 'changed the base branches inbox PRs target')
            }
        }

        return describeUserAction(logItem, "updated the team's inbox settings")
    }

    return defaultDescriber(logItem, asNotification, 'inbox settings')
}
