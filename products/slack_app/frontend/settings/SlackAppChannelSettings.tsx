import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SlackAppChannelSettingsModal } from './SlackAppChannelSettingsModal'
import { SlackAppChannelSettingsTable } from './SlackAppChannelSettingsTable'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

export function SlackAppChannelSettings(): JSX.Element {
    const { selectedIntegration, channels, channelsLoading, integrationsLoading } = useValues(slackAppSettingsLogic)
    const { openChannelModal } = useActions(slackAppSettingsLogic)

    if (integrationsLoading && !selectedIntegration) {
        return <LemonSkeleton className="h-40" />
    }
    if (!selectedIntegration) {
        return (
            <LemonBanner
                type="info"
                action={{ children: 'Go to integrations', to: urls.settings('environment-integrations') }}
            >
                Connect Slack to this project to give channels their own settings.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => openChannelModal(null)}
                    data-attr="slack-app-channel-settings-add"
                >
                    Add channel
                </LemonButton>
                <SlackAppInstallPicker />
            </div>
            {channelsLoading && channels === null ? (
                <LemonSkeleton className="h-32" />
            ) : (
                <SlackAppChannelSettingsTable integration={selectedIntegration} />
            )}
            <SlackAppChannelSettingsModal integration={selectedIntegration} />
        </div>
    )
}
