import { useActions } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TRIGGER_OPTIONS, TriggerOption, errorTrackingAlertWizardLogic } from '../errorTrackingAlertWizardLogic'
import { WizardCard } from './WizardCard'

export function TriggerStep(): JSX.Element {
    const { setTrigger, setStep } = useActions(errorTrackingAlertWizardLogic)

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
                {TRIGGER_OPTIONS.map((option: TriggerOption) => (
                    <WizardCard
                        key={option.key}
                        name={option.name}
                        description={option.description}
                        onClick={() => setTrigger(option.key)}
                    />
                ))}
            </div>
        </div>
    )
}
