import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { slackAppSettingsLogic } from './slackAppSettingsLogic'

export function SlackAppWorkspaceSettings(): JSX.Element | null {
    const { settings, settingsLoading, workspaceSettingsDisabledReason } = useValues(slackAppSettingsLogic)
    const { updateWorkspaceSettings } = useActions(slackAppSettingsLogic)

    if (settingsLoading && !settings) {
        return <LemonSkeleton className="h-16" />
    }
    // "My Slack settings" above already shows the not-connected and load-error states for the whole page.
    if (!settings) {
        return null
    }

    return (
        <div className="flex flex-col gap-1 max-w-200">
            <LemonSwitch
                bordered
                fullWidth
                label="Reply in channels shared with other organizations"
                checked={settings.workspace.external_channels_enabled}
                onChange={(checked) => updateWorkspaceSettings({ external_channels_enabled: checked })}
                disabledReason={workspaceSettingsDisabledReason}
                data-attr="slack-app-settings-external-channels"
            />
            <p className="text-secondary text-xs m-0">
                When this is off, PostHog stays quiet in Slack Connect channels. When it is on, someone in each shared
                channel still approves PostHog the first time.
            </p>
        </div>
    )
}
