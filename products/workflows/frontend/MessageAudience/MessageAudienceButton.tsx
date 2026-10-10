import { useActions, useValues } from 'kea'

import { IconSend, IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonMenu } from '@posthog/lemon-ui'

import { MessageAudience, MessageAudienceDestination, messageAudienceAccessDisabledReason } from './messageAudience'
import { messageAudienceButtonLabel, messageAudienceTooltip } from './messageAudienceReadiness'
import { messageAudienceReadinessLogic } from './messageAudienceReadinessLogic'

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

export function MessageAudienceButton(props: MessageAudienceButtonProps): JSX.Element {
    const accessDisabledReason = messageAudienceAccessDisabledReason()
    if (accessDisabledReason) {
        // No counting for someone who can't send: the button only explains why.
        return (
            <LemonButton
                type={props.type ?? 'secondary'}
                size={props.size ?? 'small'}
                fullWidth={props.fullWidth}
                icon={<IconSend />}
                disabledReason={accessDisabledReason}
                data-attr={`message-audience-${props.audience.source}`}
            >
                {props.label ?? 'Email these people'}
            </LemonButton>
        )
    }
    return <CountedMessageAudienceButton {...props} />
}

function CountedMessageAudienceButton({
    audience,
    destinations = ['broadcast', 'workflow'],
    label = 'Email these people',
    type = 'secondary',
    size = 'small',
    disabledReason,
    fullWidth,
}: MessageAudienceButtonProps): JSX.Element {
    const logic = messageAudienceReadinessLogic({ audience })
    const { readiness, navigating } = useValues(logic)
    const { open } = useActions(logic)

    // A workflow can start with nobody in the audience yet, because people enter it as they qualify.
    const broadcastDisabledReason = readiness.disabledReason ?? undefined
    const buttonProps: LemonButtonProps = {
        type,
        size,
        fullWidth,
        icon: <IconSend />,
        sideIcon: readiness.warnings.length > 0 ? <IconWarning className="text-warning" /> : undefined,
        loading: readiness.countState === 'loading' || navigating,
        disabledReason:
            disabledReason ??
            (destinations.every((destination) => destination === 'broadcast') ? broadcastDisabledReason : undefined),
        tooltip: messageAudienceTooltip(readiness),
    }
    const buttonLabel = messageAudienceButtonLabel(readiness, label)

    if (destinations.length === 1) {
        return (
            <LemonButton
                {...buttonProps}
                onClick={() => open(destinations[0])}
                data-attr={`message-audience-${audience.source}-${destinations[0]}`}
            >
                {buttonLabel}
            </LemonButton>
        )
    }
    return (
        <LemonMenu
            items={destinations.map((destination) => ({
                label: DESTINATION_LABELS[destination],
                onClick: () => open(destination),
                disabledReason: destination === 'broadcast' ? broadcastDisabledReason : undefined,
                'data-attr': `message-audience-${audience.source}-${destination}`,
            }))}
        >
            <LemonButton {...buttonProps} data-attr={`message-audience-${audience.source}`}>
                {buttonLabel}
            </LemonButton>
        </LemonMenu>
    )
}
