import { useActions } from 'kea'

import { IconAndroid, IconApple, IconLetter } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'

import { channelCatalogLogic } from './channelCatalogLogic'
import { CHANNEL_COPY, ChannelStatus, ChannelSummary } from './channelSummary'
import type { ChannelType } from './MessageChannels'

const CHANNEL_ICONS: Record<ChannelType, JSX.Element> = {
    email: <IconLetter />,
    slack: <IconSlack />,
    twilio: <IconTwilio />,
    firebase: <IconAndroid />,
    apns: <IconApple />,
}

const STATUS_TAGS: Record<ChannelStatus, { label: string; type: LemonTagType }> = {
    active: { label: 'Active', type: 'success' },
    'needs-verification': { label: 'Verify domain', type: 'warning' },
    'needs-attention': { label: 'Needs attention', type: 'danger' },
    'not-set-up': { label: 'Not set up', type: 'muted' },
}

export function ChannelCatalogCard({
    channel,
    disabledReason,
}: {
    channel: ChannelSummary
    disabledReason: string | null
}): JSX.Element {
    const { startChannelSetup } = useActions(channelCatalogLogic)
    const { name, description } = CHANNEL_COPY[channel.kind]
    const tag = STATUS_TAGS[channel.status]
    const isSetUp = channel.status !== 'not-set-up'

    return (
        <LemonCard
            hoverEffect={false}
            className="flex items-start gap-3 p-3"
            data-attr={`workflows-channel-catalog-${channel.kind}`}
        >
            <span className="text-xl shrink-0 mt-0.5">{CHANNEL_ICONS[channel.kind]}</span>
            <div className="flex flex-col gap-1 flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{name}</span>
                    <LemonTag size="small" type={tag.type}>
                        {tag.label}
                    </LemonTag>
                </div>
                <span className="text-secondary text-sm">{description}</span>
                {isSetUp && (
                    <span className="text-secondary text-xs">
                        {channel.count === 1 ? '1 connection' : `${channel.count} connections`}
                    </span>
                )}
            </div>
            <LemonButton
                size="small"
                type={isSetUp ? 'secondary' : 'primary'}
                className="shrink-0"
                onClick={() => startChannelSetup(channel.kind)}
                disabledReason={disabledReason}
                data-attr={`workflows-channel-catalog-connect-${channel.kind}`}
            >
                {isSetUp ? 'Add another' : 'Connect'}
            </LemonButton>
        </LemonCard>
    )
}
