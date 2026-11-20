import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { startEmailDomainSetup } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { isLiveOnSandboxSender } from '../Channels/sandboxSender'
import { hasOwnSender } from './hogflows/steps/email/emailStepVariants'
import { workflowLogic } from './workflowLogic'

export function WorkflowSandboxSenderBanner({ id }: { id: string }): JSX.Element | null {
    const { originalWorkflow, integrations } = useValues(workflowLogic)
    const show = !!originalWorkflow && isLiveOnSandboxSender(originalWorkflow)

    useEffect(() => {
        if (show) {
            // pinned: analytics event name
            posthog.capture('workflows sandbox sender banner shown', { workflow_id: id })
        }
    }, [show, id])

    if (!show) {
        return null
    }

    const restriction =
        'This live workflow has email steps on the PostHog test sender. Those steps reach only verified members of your organization, and everyone else is skipped.'

    const ownSender = hasOwnSender(integrations)
    // Until the senders load, the banner can't tell setup from a switch, so it offers neither.
    if (ownSender !== false) {
        return (
            <div className="shrink-0" data-attr="workflow-sandbox-sender-banner">
                <LemonBanner type="warning">
                    {ownSender
                        ? `${restriction} To reach your users, switch those steps to your verified sender.`
                        : restriction}
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="shrink-0" data-attr="workflow-sandbox-sender-banner">
            <LemonBanner
                type="warning"
                action={{
                    children: 'Set up your sending domain',
                    'data-attr': 'workflow-sandbox-sender-set-up-domain',
                    onClick: () => startEmailDomainSetup('sandbox_sender_banner'),
                }}
            >
                {restriction} To reach your users, set up your sending domain and switch those steps to it.
            </LemonBanner>
        </div>
    )
}
