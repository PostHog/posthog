import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonMenu } from '@posthog/lemon-ui'

import { MessageAudience, MessageAudienceDestination, messageAudienceAccessDisabledReason } from './messageAudience'
import { messageAudienceOpenLogic } from './messageAudienceOpenLogic'
import { MessageAudienceSpot } from './MessageAudienceSpot'

const DESTINATION_LABELS: Record<MessageAudienceDestination, string> = {
    broadcast: 'Send a one-time email',
    workflow: 'Build a custom workflow',
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
    label = 'Email these people',
    type = 'secondary',
    size = 'small',
    disabledReason,
    fullWidth,
}: MessageAudienceButtonProps): JSX.Element {
    const logic = messageAudienceOpenLogic({ audience })
    const { opening } = useValues(logic)
    const { open } = useActions(logic)
    const buttonProps = {
        type,
        size,
        disabledReason: disabledReason ?? messageAudienceAccessDisabledReason(),
        fullWidth,
        icon: <IconSend />,
        loading: opening,
    }

    if (destinations.length === 1) {
        return (
            <LemonButton
                {...buttonProps}
                onClick={() => open(destinations[0])}
                data-attr={`message-audience-${audience.source}-${destinations[0]}`}
            >
                <MessageAudienceSpot source={audience.source} destination={destinations[0]}>
                    {label}
                </MessageAudienceSpot>
            </LemonButton>
        )
    }
    return (
        <LemonMenu
            items={destinations.map((destination) => ({
                label: (
                    <MessageAudienceSpot source={audience.source} destination={destination}>
                        {DESTINATION_LABELS[destination]}
                    </MessageAudienceSpot>
                ),
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
