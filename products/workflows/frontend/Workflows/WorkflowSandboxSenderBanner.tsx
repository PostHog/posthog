import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { startEmailDomainSetup } from '../Channels/EmailDomain/emailDomainSetupLinks'
import { isLiveOnSandboxSender } from '../Channels/sandboxSender'
import { workflowLogic } from './workflowLogic'

export function WorkflowSandboxSenderBanner({ id }: { id: string }): JSX.Element | null {
    const { originalWorkflow } = useValues(workflowLogic)
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

    return (
        <div className="shrink-0" data-attr="workflow-sandbox-sender-banner">
            <LemonBanner
                type="warning"
                action={{
                    children: 'Set up your domain',
                    'data-attr': 'workflow-sandbox-sender-set-up-domain',
                    onClick: () => startEmailDomainSetup('sandbox_sender_banner'),
                }}
            >
                This workflow is live on the PostHog test sender. Only verified members of your organization receive its
                emails, and everyone else is skipped. Set up your sending domain to reach your users.
            </LemonBanner>
        </div>
    )
}
