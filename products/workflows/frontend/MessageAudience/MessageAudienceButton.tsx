import { router } from 'kea-router'

import { IconSend } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonMenu } from '@posthog/lemon-ui'

import {
    MessageAudience,
    MessageAudienceDestination,
    captureMessageAudienceClicked,
    messageAudienceUrl,
} from './messageAudience'

const DESTINATION_LABELS: Record<MessageAudienceDestination, string> = {
    broadcast: 'Send a broadcast',
    workflow: 'Start a workflow',
}

export interface MessageAudienceButtonProps extends Pick<
    LemonButtonProps,
    'type' | 'size' | 'disabledReason' | 'fullWidth'
> {
    audience: MessageAudience
    destinations?: MessageAudienceDestination[]
    label?: string
}

export function MessageAudienceButton({
    audience,
    destinations = ['broadcast', 'workflow'],
    label = 'Message these people',
    type = 'secondary',
    size = 'small',
    disabledReason,
    fullWidth,
}: MessageAudienceButtonProps): JSX.Element {
    const open = (destination: MessageAudienceDestination): void => {
        captureMessageAudienceClicked(audience.source, destination)
        router.actions.push(messageAudienceUrl(audience, destination))
    }
    const buttonProps = { type, size, disabledReason, fullWidth, icon: <IconSend /> }

    if (destinations.length === 1) {
        return (
            <LemonButton
                {...buttonProps}
                onClick={() => open(destinations[0])}
                data-attr={`message-audience-${audience.source}-${destinations[0]}`}
            >
                {label}
            </LemonButton>
        )
    }
    return (
        <LemonMenu
            items={destinations.map((destination) => ({
                label: DESTINATION_LABELS[destination],
                onClick: () => open(destination),
                'data-attr': `message-audience-${audience.source}-${destination}`,
            }))}
        >
            <LemonButton {...buttonProps} data-attr={`message-audience-${audience.source}`}>
                {label}
            </LemonButton>
        </LemonMenu>
    )
}
