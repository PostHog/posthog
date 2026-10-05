import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { WorkflowLogicProps } from './workflowLogic'
import { workflowSandboxSwitchBannerLogic } from './workflowSandboxSwitchBannerLogic'
import { WorkflowSandboxSwitchSenderButton } from './WorkflowSandboxSwitchSenderButton'

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
        <LemonBanner type="info" alignItems="start">
            <div
                className="flex flex-col gap-2 @xl:flex-row @xl:items-center"
                data-attr="workflow-sandbox-switch-banner"
            >
                <span className="min-w-0 flex-1">
                    Your project has a verified email sender. This workflow still sends from the sandbox sender, which
                    delivers only to verified members of your organization.
                </span>
                <WorkflowSandboxSwitchSenderButton
                    senders={verifiedOwnSenders}
                    disabledReason={disabledReason}
                    onSwitch={switchToOwnSender}
                />
            </div>
        </LemonBanner>
    )
}
