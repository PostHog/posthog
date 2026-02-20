import { useValues } from 'kea'

import { errorTrackingAlertWizardLogic } from './errorTrackingAlertWizardLogic'
import { ConfigureStep } from './steps/ConfigureStep'
import { DestinationStep } from './steps/DestinationStep'
import { TriggerStep } from './steps/TriggerStep'

export interface ErrorTrackingAlertWizardProps {
    onCancel: () => void
    onSwitchToTraditional: () => void
}

export function ErrorTrackingAlertWizard({
    onCancel,
    onSwitchToTraditional,
}: ErrorTrackingAlertWizardProps): JSX.Element {
    const { currentStep } = useValues(errorTrackingAlertWizardLogic)

    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="max-w-lg mx-auto flex-1 w-full">
                {currentStep === 'destination' && <DestinationStep onBack={onCancel} />}
                {currentStep === 'trigger' && <TriggerStep />}
                {currentStep === 'configure' && <ConfigureStep />}
            </div>

            <p className="text-center text-xs text-muted mt-6">
                Need more control?{' '}
                <button type="button" onClick={onSwitchToTraditional} className="text-link hover:underline">
                    Go back to traditional editor
                </button>
            </p>
        </div>
    )
}
