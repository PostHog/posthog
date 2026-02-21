import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { WizardTrigger, errorTrackingAlertWizardLogic } from '../errorTrackingAlertWizardLogic'
import { WizardCard } from './WizardCard'

export function TriggerStep(): JSX.Element {
    const { availableTriggers } = useValues(errorTrackingAlertWizardLogic)
    const { setTriggerKey, setStep } = useActions(errorTrackingAlertWizardLogic)

    return (
        <div className="space-y-4">
            <div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={() => setStep('destination')}
                >
                    Choose destination
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">What should trigger the alert?</h2>
                <p className="text-secondary text-sm">Choose when you want to be notified</p>
            </div>
            <div className="space-y-3">
                {availableTriggers.map((trigger: WizardTrigger) => (
                    <WizardCard
                        key={trigger.key}
                        name={trigger.name}
                        description={trigger.description}
                        onClick={() => setTriggerKey(trigger.key)}
                    />
                ))}
            </div>
        </div>
    )
}
