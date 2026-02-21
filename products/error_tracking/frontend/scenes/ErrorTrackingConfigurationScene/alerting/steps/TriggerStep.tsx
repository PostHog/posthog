import { useActions, useValues } from 'kea'

import { WizardTrigger, errorTrackingAlertWizardLogic } from '../errorTrackingAlertWizardLogic'
import { WizardCard } from './WizardCard'

export function TriggerStep(): JSX.Element {
    const { availableTriggers } = useValues(errorTrackingAlertWizardLogic)
    const { setTriggerKey } = useActions(errorTrackingAlertWizardLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">What should trigger the alert?</h2>
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
