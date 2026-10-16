import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { WorkflowsEmailTrackingConsentSettings } from '../../scenes/settings/WorkflowsEmailTrackingConsentSettings'
import { WorkflowsEngagementEventsSettings } from '../../scenes/settings/WorkflowsEngagementEventsSettings'
import { FrequencyCapPreset } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

const ADMIN_ONLY_REASON = 'Only project admins can change the frequency cap'

function SendingRule({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: JSX.Element
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

/** The project-wide sending rules, with a frequency cap picked for a new setup so people do not get flooded. */
export function WizardSendingRulesStep(): JSX.Element {
    const { shownFrequencyCap, savedFrequencyCap, canEditSendingRules } = useValues(workflowsOnboardingWizardLogic)
    const { setFrequencyCapChoice } = useActions(workflowsOnboardingWizardLogic)
    const disabledReason = canEditSendingRules ? undefined : ADMIN_ONLY_REASON

    const options: LemonRadioOption<FrequencyCapPreset>[] = [
        {
            value: 'recommended',
            label: 'At most 1 email every 2 days (recommended)',
            description: 'Keeps marketing email from piling up when several workflows target the same person.',
        },
        { value: 'weekly', label: 'At most 3 emails a week' },
        {
            value: 'off',
            label: 'No cap',
            description: 'Each workflow and broadcast sends on its own schedule.',
        },
    ]
    if (shownFrequencyCap === 'custom') {
        options.unshift({
            value: 'custom',
            label: `At most ${savedFrequencyCap.maxMessages} emails every ${savedFrequencyCap.windowDays} days`,
            description: 'Your current cap. Change the numbers in Messaging settings.',
        })
    }

    return (
        <div className="flex flex-col gap-6">
            <SendingRule
                title="Frequency cap"
                description="The most marketing emails one person gets across all workflows and broadcasts. Transactional email is never capped."
            >
                <LemonRadio
                    value={shownFrequencyCap}
                    onChange={setFrequencyCapChoice}
                    options={options.map((option) => ({
                        ...option,
                        disabledReason,
                        'data-attr': `workflows-onboarding-wizard-frequency-cap-${option.value}`,
                    }))}
                    aria-label="Frequency cap"
                />
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
                <WorkflowsEngagementEventsSettings />
            </SendingRule>
        </div>
    )
}
