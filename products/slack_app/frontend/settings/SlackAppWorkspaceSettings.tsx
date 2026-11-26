import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { slackAppSettingsLogic } from './slackAppSettingsLogic'

export function SlackAppWorkspaceSettings(): JSX.Element {
    const { settings, settingsLoading, workspaceSettingsDisabledReason } = useValues(slackAppSettingsLogic)
    const { updateWorkspaceSettings } = useActions(slackAppSettingsLogic)

    if (settingsLoading && !settings) {
        return <LemonSkeleton className="h-16" />
    }
    if (!settings) {
        return (
            <LemonBanner type="error">Couldn't load the workspace settings. Refresh the page to try again.</LemonBanner>
        )
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
