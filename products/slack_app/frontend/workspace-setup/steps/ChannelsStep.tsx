import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonInputSelect } from '@posthog/lemon-ui'

import { slackAppWorkspaceSetupLogic } from '../slackAppWorkspaceSetupLogic'

export function ChannelsStep(): JSX.Element {
    const {
        joinableChannels,
        joinedChannelNames,
        channelOptionsLoading,
        selectedChannelIds,
        postWelcome,
        joinResultsLoading,
    } = useValues(slackAppWorkspaceSetupLogic)
    const { setSelectedChannelIds, setPostWelcome, joinChannels, skipStep } = useActions(slackAppWorkspaceSetupLogic)

    const count = selectedChannelIds.length

    return (
        <>
            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-2xl font-bold m-0">Which channels should PostHog join?</h1>
                <p className="text-secondary m-0">
                    PostHog answers only when someone mentions @PostHog. You can invite it to more channels later with
                    /invite @PostHog.
                </p>
            </div>

            <div className="flex flex-col gap-2 w-full">
                <LemonInputSelect
                    mode="multiple"
                    fullWidth
                    loading={channelOptionsLoading}
                    placeholder="Search public channels"
                    value={selectedChannelIds}
                    onChange={setSelectedChannelIds}
                    options={joinableChannels.map((channel) => ({ key: channel.id, label: `#${channel.name}` }))}
                    data-attr="slack-app-workspace-setup-channels"
                />
                {joinedChannelNames.length > 0 ? (
                    <p className="text-xs text-secondary m-0">
                        PostHog is already in {joinedChannelNames.map((name) => `#${name}`).join(', ')}.
                    </p>
                ) : null}
                <LemonCheckbox
                    checked={postWelcome}
                    onChange={setPostWelcome}
                    label="Post a short welcome message in each channel"
                />
            </div>

            <div className="flex flex-wrap justify-between items-center gap-2 w-full">
                <LemonButton type="tertiary" onClick={() => skipStep('channels')}>
                    Skip
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={joinResultsLoading}
                    disabledReason={count === 0 ? 'Choose at least one channel' : undefined}
                    onClick={joinChannels}
                    data-attr="slack-app-workspace-setup-join-channels"
                >
                    {count > 1 ? `Add PostHog to ${count} channels` : 'Add PostHog to this channel'}
                </LemonButton>
            </div>
        </>
    )
}
