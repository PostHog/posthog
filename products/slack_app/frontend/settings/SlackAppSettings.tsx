import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SlackAppChannelSettings } from './SlackAppChannelSettings'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { SlackAppPersonalSettings } from './SlackAppPersonalSettings'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import { SlackAppWorkspaceSettings } from './SlackAppWorkspaceSettings'

export function SlackAppSettings(): JSX.Element {
    const { slackIntegrations, integrationsLoading, activeTab } = useValues(slackAppSettingsLogic)
    const { setActiveTab } = useActions(slackAppSettingsLogic)

    if (integrationsLoading && !slackIntegrations?.length) {
        return <LemonSkeleton className="h-60" />
    }
    if (!slackIntegrations?.length) {
        return (
            <LemonBanner
                type="info"
                action={{ children: 'Go to integrations', to: urls.settings('environment-integrations') }}
            >
                Connect Slack to this project to change how PostHog works in Slack.
            </LemonBanner>
        )
    }

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={setActiveTab}
            rightSlot={<SlackAppInstallPicker />}
            data-attr="slack-app-settings-tabs"
            tabs={[
                {
                    key: 'personal',
                    label: 'Personal',
                    content: <SlackAppPersonalSettings />,
                },
                {
                    key: 'channels',
                    label: 'Channels',
                    content: <SlackAppChannelSettings />,
                },
                {
                    key: 'workspace',
                    label: 'Workspace',
                    content: <SlackAppWorkspaceSettings />,
                },
            ]}
        />
    )
}
