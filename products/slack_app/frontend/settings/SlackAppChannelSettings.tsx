import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { SlackAppChannelSettingsModal } from './SlackAppChannelSettingsModal'
import { SlackAppChannelSettingsTable } from './SlackAppChannelSettingsTable'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

export function SlackAppChannelSettings(): JSX.Element {
    const { selectedIntegration, channels, channelsLoading, channelsLoadFailed } = useValues(slackAppSettingsLogic)
    const { openChannelModal, loadChannels } = useActions(slackAppSettingsLogic)

    if (!selectedIntegration) {
        return <LemonSkeleton className="h-40" />
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-secondary m-0 max-w-160">
                    A channel's project and repository win over each person's own. Its question mode can only make
                    things stricter. Each organization keeps its own channel settings.
                </p>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => openChannelModal(null)}
                    // Adding before the list loads could replace a channel's settings without showing them first.
                    disabledReason={channels === null ? 'Wait for the channel list to load' : undefined}
                    data-attr="slack-app-channel-settings-add"
                >
                    Add channel
                </LemonButton>
            </div>
            {channelsLoading && channels === null ? (
                <LemonSkeleton className="h-32" />
            ) : channelsLoadFailed ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadChannels() }}>
                    Couldn't load the channel settings.
                </LemonBanner>
            ) : (
                <SlackAppChannelSettingsTable integration={selectedIntegration} />
            )}
            <SlackAppChannelSettingsModal integration={selectedIntegration} />
        </div>
    )
}
