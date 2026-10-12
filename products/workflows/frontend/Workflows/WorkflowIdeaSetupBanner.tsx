import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { emailStepsMissingSender, ideaEmailSender, withEmailSender } from '../setupGuide/ideas/ideaEmailSender'
import { onboardingWizardUrl } from '../setupGuide/wizard/onboardingWizardSteps'
import { workflowLogic } from './workflowLogic'

/** The steps left before a workflow PostHog drafted can send, shown while it is still a draft. */
export function WorkflowIdeaSetupBanner(): JSX.Element | null {
    const { workflow } = useValues(workflowLogic)
    const { setWorkflowInfo } = useActions(workflowLogic)
    const { integrations } = useValues(integrationsLogic)

    if (workflow?.origin_product !== 'ideas' || workflow.status !== 'draft') {
        return null
    }
    const sender = ideaEmailSender(integrations)
    const actions = workflow.actions as unknown as Record<string, any>[]
    const missing = emailStepsMissingSender(actions)

    let banner: JSX.Element
    if (sender.status === 'verified' && missing > 0) {
        banner = (
            <LemonBanner
                type="info"
                action={{
                    children: `Send from ${sender.address}`,
                    onClick: () =>
                        setWorkflowInfo({
                            actions: withEmailSender({ actions }, sender.integrationId)
                                .actions as typeof workflow.actions,
                        }),
                    'data-attr': 'workflow-idea-apply-sender',
                }}
            >
                {missing === 1 ? 'One email has' : `${missing} emails have`} no sender yet. Send them from your verified
                address, then send yourself a test from the Test tab.
            </LemonBanner>
        )
    } else if (sender.status === 'none' || sender.status === 'unverified') {
        banner = (
            <LemonBanner
                type="warning"
                action={{
                    children: sender.status === 'none' ? 'Set up email sending' : 'Finish verifying your domain',
                    to:
                        sender.status === 'none'
                            ? onboardingWizardUrl('messaging', { step: 'channel' })
                            : urls.workflows('channels'),
                    'data-attr': 'workflow-idea-banner-sender',
                }}
            >
                These emails can't send until your project has a verified sender on your own domain. This draft stays
                here while you set one up.
            </LemonBanner>
        )
    } else {
        banner = (
            <LemonBanner type="info">
                Before you turn this on, read the emails, check where the buttons link, and send yourself a test from
                the Test tab.
            </LemonBanner>
        )
    }

    return (
        // LemonBanner drops data-attr, so the wrapper carries it. pinned: data-attr - autocapture dashboards read it
        <div className="shrink-0" data-attr="workflow-idea-setup-banner">
            {banner}
        </div>
    )
}
