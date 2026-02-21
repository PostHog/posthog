import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizardStepper } from './AlertWizardStepper'
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
    const { setStep } = useActions(errorTrackingAlertWizardLogic)

    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="grid grid-cols-[1fr_auto_1fr] items-center">
                <div />
                <AlertWizardStepper currentStep={currentStep} onStepClick={setStep} />
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconX />}
                    onClick={onCancel}
                    aria-label="Close wizard"
                    className="justify-self-start ml-2"
                />
            </div>

            <div className="max-w-lg mx-auto flex-1 w-full mt-4">
                {currentStep === 'destination' && <DestinationStep />}
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
