import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'

import { IntegrationType } from '~/types'

import { isVerifiedEmailSender } from '../Channels/defaultEmailSender'
import {
    captureEmailDomainSetupStarted,
    emailDomainSetupPath,
    startEmailDomainSetup,
} from '../Channels/EmailDomain/emailDomainSetupLinks'
import { isLiveOnSandboxSender } from '../Channels/sandboxSender'
import { hasDeliverableSender } from './hogflows/steps/email/emailStepVariants'
import { workflowLogic } from './workflowLogic'

function nextStepFor(integrations: IntegrationType[] | null): { nextStep: string | null; action?: LemonBannerAction } {
    const ownSender = hasDeliverableSender(integrations)
    // Until the senders load, the banner can't tell setup from a switch, so it offers neither.
    if (ownSender === null) {
        return { nextStep: null }
    }
    if (ownSender) {
        return { nextStep: 'To reach your users, switch those steps to your verified sender.' }
    }
    const stoppedSender = integrations?.find(isVerifiedEmailSender)
    if (stoppedSender) {
        return {
            nextStep: 'To reach your users, fix your sending domain and switch those steps to it.',
            action: {
                children: 'Fix your sending domain',
                'data-attr': 'workflow-sandbox-sender-fix-domain',
                to: emailDomainSetupPath(stoppedSender.id),
                onClick: () => captureEmailDomainSetupStarted('sandbox_sender_banner_repair'),
            },
        }
    }
    return {
        nextStep: 'To reach your users, set up your sending domain and switch those steps to it.',
        action: {
            children: 'Set up your sending domain',
            'data-attr': 'workflow-sandbox-sender-set-up-domain',
            onClick: () => startEmailDomainSetup('sandbox_sender_banner'),
        },
    }
}

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

    const { nextStep, action } = nextStepFor(integrations)

    return (
        <div className="shrink-0" data-attr="workflow-sandbox-sender-banner">
            <LemonBanner type="warning" action={action}>
                {nextStep ? `${restriction} ${nextStep}` : restriction}
            </LemonBanner>
        </div>
    )
}
