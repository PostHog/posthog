import { useActions, useValues } from 'kea'

import { LemonBanner, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import { SlackAppChannelSettingsTable } from './SlackAppChannelSettingsTable'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

export function SlackAppChannelSettings(): JSX.Element {
    const { selectedIntegration, channels, channelsLoading, integrationsLoading } = useValues(slackAppSettingsLogic)
    const { addChannel } = useActions(slackAppSettingsLogic)

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
            <div className="flex flex-wrap items-end justify-between gap-2">
                <div className="flex flex-col gap-1 w-80">
                    <LemonLabel>Add a channel</LemonLabel>
                    <SlackChannelPicker
                        integration={selectedIntegration}
                        value={undefined}
                        onChange={(value) => value && addChannel(value.split('|')[0])}
                    />
                </div>
                <SlackAppInstallPicker />
            </div>
            {channelsLoading && channels === null ? (
                <LemonSkeleton className="h-32" />
            ) : (
                <SlackAppChannelSettingsTable integration={selectedIntegration} />
            )}
        </div>
    )
}
