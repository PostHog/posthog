import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import {
    FREQUENCY_CAP_HOLD_HELP,
    FREQUENCY_CAP_HOLD_INFO,
    MAX_FREQUENCY_CAP_HOLD_HOURS,
    MAX_FREQUENCY_CAP_MESSAGES,
    MAX_FREQUENCY_CAP_WINDOW_DAYS,
    frequencyCapFieldError,
    frequencyCapHoldError,
    toFrequencyCapInputValue,
} from '../../scenes/settings/frequencyCap'
import { WorkflowsEmailTrackingConsentSettings } from '../../scenes/settings/WorkflowsEmailTrackingConsentSettings'
import { FrequencyCapChoice } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

const CAP_OPTIONS: LemonRadioOption<FrequencyCapChoice>[] = [
    {
        value: 'recommended',
        label: 'At most 1 email every 2 days (recommended)',
        description: 'Keeps marketing email from piling up when several workflows reach the same person.',
    },
    { value: 'off', label: 'No cap', description: 'Each workflow and broadcast sends on its own schedule.' },
    { value: 'custom', label: 'Set your own cap' },
]

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
    const {
        shownFrequencyCapChoice,
        shownCustomFrequencyCap,
        shownHoldHours,
        sendingRulesDisabledReason,
        shownEngagementEvents,
    } = useValues(workflowsOnboardingWizardLogic)
    const { setFrequencyCapChoice, setCustomFrequencyCap, setHoldHours, setEngagementEventsChoice } =
        useActions(workflowsOnboardingWizardLogic)
    const disabledReason = sendingRulesDisabledReason ?? undefined
    const { maxMessages, windowDays } = shownCustomFrequencyCap

    return (
        <div className="flex flex-col gap-6">
            <SendingRule
                title="Frequency cap"
                description="The most marketing emails one person gets across all workflows and broadcasts. Transactional email is never capped. When you schedule a broadcast, its calendar suggests a day within this cap. With no cap, it keeps sends to the same people 2 days apart."
            >
                <LemonRadio
                    value={shownFrequencyCapChoice}
                    onChange={setFrequencyCapChoice}
                    aria-label="Frequency cap"
                    options={CAP_OPTIONS.map((option) => ({
                        ...option,
                        disabledReason,
                        'data-attr': `workflows-onboarding-wizard-frequency-cap-${option.value}`,
                    }))}
                />
                {shownFrequencyCapChoice === 'custom' && (
                    <div className="flex flex-wrap gap-4 pl-6">
                        <LemonField.Pure
                            className="flex-1 min-w-60"
                            label="Messages per person"
                            htmlFor="workflows-onboarding-wizard-frequency-cap-max-messages"
                            error={frequencyCapFieldError(maxMessages, windowDays, MAX_FREQUENCY_CAP_MESSAGES)}
                        >
                            <LemonInput
                                id="workflows-onboarding-wizard-frequency-cap-max-messages"
                                type="number"
                                min={1}
                                max={MAX_FREQUENCY_CAP_MESSAGES}
                                value={maxMessages ?? undefined}
                                onChange={(value) =>
                                    setCustomFrequencyCap({ maxMessages: toFrequencyCapInputValue(value), windowDays })
                                }
                                disabledReason={disabledReason}
                                data-attr="workflows-onboarding-wizard-frequency-cap-max-messages"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            className="flex-1 min-w-60"
                            label="Within this many days"
                            htmlFor="workflows-onboarding-wizard-frequency-cap-window-days"
                            error={frequencyCapFieldError(windowDays, maxMessages, MAX_FREQUENCY_CAP_WINDOW_DAYS)}
                        >
                            <LemonInput
                                id="workflows-onboarding-wizard-frequency-cap-window-days"
                                type="number"
                                min={1}
                                max={MAX_FREQUENCY_CAP_WINDOW_DAYS}
                                value={windowDays ?? undefined}
                                onChange={(value) =>
                                    setCustomFrequencyCap({ maxMessages, windowDays: toFrequencyCapInputValue(value) })
                                }
                                disabledReason={disabledReason}
                                data-attr="workflows-onboarding-wizard-frequency-cap-window-days"
                            />
                        </LemonField.Pure>
                    </div>
                )}
                {shownFrequencyCapChoice !== 'off' && (
                    <LemonField.Pure
                        className="max-w-80"
                        label="Hold capped messages for up to (hours)"
                        info={FREQUENCY_CAP_HOLD_INFO}
                        help={FREQUENCY_CAP_HOLD_HELP}
                        htmlFor="workflows-onboarding-wizard-frequency-cap-hold-hours"
                        error={frequencyCapHoldError(shownHoldHours)}
                    >
                        <LemonInput
                            id="workflows-onboarding-wizard-frequency-cap-hold-hours"
                            type="number"
                            min={1}
                            max={MAX_FREQUENCY_CAP_HOLD_HOURS}
                            value={shownHoldHours ?? undefined}
                            onChange={(value) => setHoldHours(toFrequencyCapInputValue(value))}
                            placeholder="Don't hold"
                            disabledReason={disabledReason}
                            data-attr="workflows-onboarding-wizard-frequency-cap-hold-hours"
                        />
                    </LemonField.Pure>
                )}
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
                    disabledReason={disabledReason}
                    data-attr="workflows-onboarding-wizard-engagement-events"
                />
            </SendingRule>
        </div>
    )
}
