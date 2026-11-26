import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SlackIntegrationInactiveBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import type { IntegrationType } from '~/types'

import type { SlackAppChannelSettingsApi, SlackChannelQuestionModeEnumApi } from '../generated/api.schemas'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import { slackChannelLabel } from './slackChannelLabel'

const QUESTION_MODE_TAGS: Record<SlackChannelQuestionModeEnumApi, string> = {
    ask: 'Asks before answering',
    never: '@-mentions only',
}

function ChannelSettingTags({ channel }: { channel: SlackAppChannelSettingsApi }): JSX.Element {
    const { projectNames } = useValues(slackAppSettingsLogic)

    return (
        <div className="flex flex-wrap items-center gap-1">
            {channel.default_integration_id !== null ? (
                <LemonTag>{projectNames[channel.default_integration_id] ?? 'Unknown project'}</LemonTag>
            ) : null}
            {channel.default_repository ? (
                <LemonTag icon={<IconGithub />}>{channel.default_repository}</LemonTag>
            ) : null}
            {channel.untagged_question_mode ? (
                <LemonTag>{QUESTION_MODE_TAGS[channel.untagged_question_mode]}</LemonTag>
            ) : null}
        </div>
    )
}

export function SlackAppChannelSettingsTable({ integration }: { integration: IntegrationType }): JSX.Element {
    const { channels } = useValues(slackAppSettingsLogic)
    const { openChannelModal, removeChannel } = useActions(slackAppSettingsLogic)
    const channelLogic = slackIntegrationLogic({ id: integration.id })
    const { slackChannels, allSlackChannelsLoading, attemptedSlackChannelIds, slackIntegrationInactiveMessage } =
        useValues(channelLogic)
    const { loadAllSlackChannels, loadSlackChannelById } = useActions(channelLogic)

    useEffect(() => {
        if (!channelLogic.values.slackChannels.length && !channelLogic.values.allSlackChannelsLoading) {
            loadAllSlackChannels()
        }
    }, [channelLogic, loadAllSlackChannels])

    // A saved channel past the first page of the channel list needs its own lookup to show its name.
    useEffect(() => {
        if (allSlackChannelsLoading) {
            return
        }
        for (const channel of channels ?? []) {
            const id = channel.slack_channel_id
            if (!attemptedSlackChannelIds[id] && !slackChannels.some((slackChannel) => slackChannel.id === id)) {
                loadSlackChannelById(id)
            }
        }
    }, [channels, slackChannels, allSlackChannelsLoading, attemptedSlackChannelIds, loadSlackChannelById])

    return (
        <>
            {slackIntegrationInactiveMessage ? (
                <SlackIntegrationInactiveBanner message={slackIntegrationInactiveMessage} />
            ) : null}
            <LemonTable
                dataSource={channels ?? []}
                rowKey="slack_channel_id"
                onRow={(channel) => ({ onClick: () => openChannelModal(channel), className: 'cursor-pointer' })}
                emptyState="No channel has its own settings yet."
                columns={[
                    {
                        title: 'Channel',
                        key: 'channel',
                        render: (_, channel) => {
                            const slackChannel = slackChannels.find((c) => c.id === channel.slack_channel_id)
                            return (
                                <div className="py-1">
                                    <div className="flex items-center gap-2 font-semibold">
                                        {slackChannelLabel(slackChannel, channel.slack_channel_id)}
                                        {slackChannel?.is_ext_shared ? (
                                            <LemonTag size="small" type="muted">
                                                Shared
                                            </LemonTag>
                                        ) : null}
                                    </div>
                                    {channel.updated_by_name && channel.updated_at ? (
                                        <div className="text-secondary text-xs">
                                            Changed by {channel.updated_by_name} <TZLabel time={channel.updated_at} />
                                        </div>
                                    ) : null}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Settings',
                        key: 'settings',
                        render: (_, channel) => <ChannelSettingTags channel={channel} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, channel) => (
                            <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => openChannelModal(channel)}
                                    data-attr="slack-app-channel-settings-edit"
                                >
                                    Edit
                                </LemonButton>
                                <More
                                    data-attr="slack-app-channel-settings-more"
                                    overlay={
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: 'Remove channel settings',
                                                    status: 'danger',
                                                    onClick: () => removeChannel(channel.slack_channel_id),
                                                    'data-attr': 'slack-app-channel-settings-remove',
                                                },
                                            ]}
                                        />
                                    }
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </>
    )
}
