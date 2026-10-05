import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

export function WorkflowSandboxSwitchSenderButton({
    senders,
    disabledReason,
    onSwitch,
}: {
    senders: IntegrationType[]
    disabledReason: string | null
    onSwitch: (integrationId: number) => void
}): JSX.Element {
    const buttonProps = {
        type: 'secondary' as const,
        size: 'small' as const,
        disabledReason,
        'data-attr': 'workflow-sandbox-switch-sender',
        className: 'max-w-full shrink-0 self-start @xl:self-auto',
    }

    if (senders.length === 1) {
        const email: string = senders[0].config.email
        return (
            <LemonButton {...buttonProps} truncate tooltip={email} onClick={() => onSwitch(senders[0].id)}>
                {`Switch to ${email}`}
            </LemonButton>
        )
    }

    return (
        <LemonMenu
            items={senders.map((sender) => ({
                label: sender.display_name,
                onClick: () => onSwitch(sender.id),
                'data-attr': 'workflow-sandbox-switch-sender-option',
            }))}
            placement="bottom-end"
        >
            <LemonButton {...buttonProps}>Switch sender</LemonButton>
        </LemonMenu>
    )
}
