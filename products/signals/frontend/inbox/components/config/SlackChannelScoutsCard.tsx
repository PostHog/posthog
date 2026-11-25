import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { slackChannelScoutLogic } from '../../logics/slackChannelScoutLogic'
import { ConfigCardHeader } from './ConfigCardHeader'
import { SlackChannelScoutModal } from './SlackChannelScoutModal'

export function SlackChannelScoutsCard(): JSX.Element {
    const { channelSources, channelSourcesLoading, slackScouts } = useValues(slackChannelScoutLogic)
    const { openSlackScoutModal, loadChannelSources } = useActions(slackChannelScoutLogic)

    const syncedChannelCount =
        channelSources?.reduce(
            (count, source) => count + source.channels.filter((channel) => channel.table_name !== null).length,
            0
        ) ?? 0

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-3" data-attr="signal-slack-scouts-card">
            <ConfigCardHeader
                icon={<IconSlack className="size-5 shrink-0 mt-0.5" />}
                title="Slack channels"
                description="Pick channels for a scout to read. It files a report when people raise a problem or request worth acting on."
            />
            {channelSources === null && channelSourcesLoading ? (
                <LemonSkeleton className="h-8" />
            ) : channelSources === null ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Retry', onClick: () => loadChannelSources() }}
                    className="w-full"
                >
                    Couldn't load your Slack channels.
                </LemonBanner>
            ) : channelSources.length === 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-secondary">
                        Connect Slack as a data warehouse source to sync channel messages.
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.dataWarehouseSourceNew('Slack', urls.inbox('sources'), 'Inbox sources')}
                        data-attr="signal-slack-scouts-connect"
                    >
                        Connect Slack
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-secondary">
                        {slackScouts && slackScouts.length > 0 ? (
                            <>
                                {slackScouts.length} Slack {slackScouts.length === 1 ? 'scout' : 'scouts'}:{' '}
                                {slackScouts.map((scout, index) => (
                                    <span key={scout.id}>
                                        {index > 0 && ', '}
                                        <Link to={urls.inboxScout(scout.skill_name)}>
                                            {scout.display_name || scout.skill_name}
                                        </Link>
                                    </span>
                                ))}
                            </>
                        ) : (
                            `${syncedChannelCount} synced ${syncedChannelCount === 1 ? 'channel' : 'channels'} available.`
                        )}
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={openSlackScoutModal}
                        disabledReason={
                            syncedChannelCount === 0
                                ? 'No channel has synced yet. Turn on channels in the Slack source and wait for the first sync.'
                                : undefined
                        }
                        data-attr="signal-slack-scouts-create"
                    >
                        New Slack scout
                    </LemonButton>
                </div>
            )}
            <SlackChannelScoutModal />
        </LemonCard>
    )
}
