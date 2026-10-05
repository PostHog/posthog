import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, IntegrationType } from '~/types'

import { WorkflowLogicProps } from './workflowLogic'
import { workflowSandboxSwitchBannerLogic } from './workflowSandboxSwitchBannerLogic'

export function WorkflowSandboxSwitchBanner(props: WorkflowLogicProps): JSX.Element | null {
    const logic = workflowSandboxSwitchBannerLogic(props)
    const { bannerVisible, verifiedOwnSenders, workflowUserAccessLevel } = useValues(logic)
    const { switchToOwnSender } = useActions(logic)

    if (!bannerVisible) {
        return null
    }

    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return (
        <LemonBanner type="info" data-attr="workflow-sandbox-switch-banner">
            <div className="flex flex-col gap-2 @md:flex-row @md:items-center">
                <span className="grow">
                    Your own email sender is verified. This workflow still sends from the sandbox sender, which only
                    delivers to members of your organization.
                </span>
                <SwitchSenderButton
                    senders={verifiedOwnSenders}
                    disabledReason={disabledReason}
                    onSwitch={switchToOwnSender}
                />
            </div>
        </LemonBanner>
    )
}

function SwitchSenderButton({
    senders,
    disabledReason,
    onSwitch,
}: {
    senders: IntegrationType[]
    disabledReason: string | undefined
    onSwitch: (integrationId: number) => void
}): JSX.Element {
    const buttonProps = {
        type: 'secondary' as const,
        size: 'small' as const,
        disabledReason,
        'data-attr': 'workflow-sandbox-switch-sender',
        className: 'shrink-0',
    }

    if (senders.length === 1) {
        return (
            <LemonButton {...buttonProps} onClick={() => onSwitch(senders[0].id)}>
                {`Switch to ${senders[0].config.email}`}
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
