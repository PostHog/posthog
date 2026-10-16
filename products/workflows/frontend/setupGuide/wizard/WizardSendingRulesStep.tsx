import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { WorkflowsEmailTrackingConsentSettings } from '../../scenes/settings/WorkflowsEmailTrackingConsentSettings'
import { RECOMMENDED_FREQUENCY_CAP } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

function SendingRule({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <div>
                <h3 className="mb-0.5 text-base font-semibold">{title}</h3>
                <p className="mb-0 text-sm text-secondary">{description}</p>
            </div>
            {children}
        </section>
    )
}

export function WizardSendingRulesStep(): JSX.Element {
    const { savedFrequencyCap, canEditSendingRules, shownEngagementEvents } = useValues(workflowsOnboardingWizardLogic)
    const { setEngagementEventsChoice } = useActions(workflowsOnboardingWizardLogic)

    const hasSavedCap = savedFrequencyCap.maxMessages !== null && savedFrequencyCap.windowDays !== null
    const cap = hasSavedCap ? savedFrequencyCap : RECOMMENDED_FREQUENCY_CAP
    const isRecommended =
        cap.maxMessages === RECOMMENDED_FREQUENCY_CAP.maxMessages &&
        cap.windowDays === RECOMMENDED_FREQUENCY_CAP.windowDays

    return (
        <div className="flex flex-col gap-6">
            <SendingRule
                title="Frequency cap"
                description="The most marketing emails one person gets across all workflows and broadcasts. Transactional email is never capped."
            >
                <div className="flex flex-wrap items-center gap-2 rounded border bg-surface-primary px-3 py-2">
                    <span className="font-semibold">
                        {`At most ${pluralize(cap.maxMessages ?? 0, 'email')} every ${pluralize(cap.windowDays ?? 0, 'day')}`}
                    </span>
                    {isRecommended && <LemonTag type="success">Recommended</LemonTag>}
                </div>
                <p className="mb-0 text-sm text-secondary">
                    {!hasSavedCap && !canEditSendingRules ? 'Only project admins can set the frequency cap. ' : null}
                    To set a different cap or turn it off, go to{' '}
                    <Link to={urls.workflows('settings')} data-attr="workflows-onboarding-wizard-messaging-settings">
                        Messaging settings
                    </Link>
                    .
                </p>
            </SendingRule>
            <LemonDivider className="my-0" />
            <SendingRule
                title="Email tracking consent"
                description="Whether tracking opens and clicks on marketing email needs the recipient's consent."
            >
                <WorkflowsEmailTrackingConsentSettings />
            </SendingRule>
            <LemonDivider className="my-0" />
            <SendingRule
                title="Engagement events"
                description="Capture sends, opens, clicks and bounces as PostHog events, so you can use them in insights and funnels. These events count toward your event usage."
            >
                <LemonSwitch
                    checked={shownEngagementEvents}
                    onChange={setEngagementEventsChoice}
                    label="Capture email engagement events"
                    bordered
                    data-attr="workflows-onboarding-wizard-engagement-events"
                />
            </SendingRule>
        </div>
    )
}
