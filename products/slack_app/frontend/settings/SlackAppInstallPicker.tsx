import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { slackAppSettingsLogic } from './slackAppSettingsLogic'

/** Lets a project with more than one Slack workspace pick the one to change. Renders nothing for one workspace. */
export function SlackAppInstallPicker(): JSX.Element | null {
    const { slackIntegrations, selectedIntegrationId } = useValues(slackAppSettingsLogic)
    const { selectIntegration } = useActions(slackAppSettingsLogic)

    if (!slackIntegrations || slackIntegrations.length < 2) {
        return null
    }

    return (
        <LemonSelect
            value={selectedIntegrationId}
            onChange={(integrationId) => integrationId !== null && selectIntegration(integrationId)}
            options={slackIntegrations.map((integration) => ({
                value: integration.id,
                label: integration.display_name,
            }))}
            data-attr="slack-app-settings-workspace-picker"
        />
    )
}
