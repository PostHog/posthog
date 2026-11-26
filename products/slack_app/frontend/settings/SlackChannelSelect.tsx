import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSearchableSelect } from '@posthog/lemon-ui'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { IconSlackExternal } from 'lib/lemon-ui/icons'

import type { IntegrationType } from '~/types'

import { slackChannelLabel } from './slackChannelLabel'

/** A dropdown of the workspace's Slack channels. Search filters the loaded page and also asks the server, like the shared Slack channel picker. */
export function SlackChannelSelect({
    integration,
    value,
    onChange,
    disabledReason,
}: {
    integration: IntegrationType
    value: string | null
    onChange: (slackChannelId: string) => void
    disabledReason?: string
}): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const { slackChannels, allSlackChannelsLoading } = useValues(logic)
    const { loadAllSlackChannels } = useActions(logic)

    useEffect(() => {
        if (!logic.values.slackChannels.length && !logic.values.allSlackChannelsLoading) {
            loadAllSlackChannels()
        }
    }, [logic, loadAllSlackChannels])

    const options = slackChannels
        .filter((channel) => channel.name)
        .map((channel) => ({
            value: channel.id,
            label: slackChannelLabel(channel, channel.id),
            labelInMenu: (
                <span className="flex items-center gap-2">
                    {slackChannelLabel(channel, channel.id)}
                    {channel.is_ext_shared ? <IconSlackExternal /> : null}
                </span>
            ),
        }))
    const selected = value ? slackChannels.find((channel) => channel.id === value) : undefined
    if (value && !selected) {
        options.unshift({ value, label: value, labelInMenu: <span>{value}</span> })
    }

    return (
        <LemonSearchableSelect
            fullWidth
            value={value ?? undefined}
            onChange={(channelId) => channelId && onChange(channelId)}
            options={options}
            loading={allSlackChannelsLoading}
            placeholder="Select a channel"
            searchPlaceholder="Search channels"
            noResultsMessage={allSlackChannelsLoading ? 'Loading channels...' : 'No channel matches'}
            onSearchChange={(term) => loadAllSlackChannels(false, term)}
            disabledReason={disabledReason}
            searchInputDataAttr="slack-app-channel-settings-channel-search"
            menu={{ className: '!max-h-80' }}
            data-attr="slack-app-channel-settings-channel"
        />
    )
}
