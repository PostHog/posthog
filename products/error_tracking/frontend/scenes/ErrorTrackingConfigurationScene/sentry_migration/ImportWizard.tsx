import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, TooltipProvider, cn } from '@posthog/quill'

import { ImportSourceStep } from './ImportSourceStep'
import { ImportWizardStepper, ImportWizardStepperStep } from './ImportWizardStepper'
import { SentryImportStep } from './SentryImportStep'
import { SentryLocationStep } from './SentryLocationStep'
import { ImportWizardStep, sentryMigrationLogic } from './sentryMigrationLogic'
import { SentryTokenStep } from './SentryTokenStep'

const STEPS: ImportWizardStepperStep<ImportWizardStep>[] = [
    { key: ImportWizardStep.Source, label: 'Tool' },
    { key: ImportWizardStep.Location, label: 'URL' },
    { key: ImportWizardStep.Token, label: 'Token' },
    { key: ImportWizardStep.Import, label: 'Import' },
]

export function ImportWizard(): JSX.Element {
    const { step } = useValues(sentryMigrationLogic)
    const { setStep, resetWizard } = useActions(sentryMigrationLogic)

    return (
        <TooltipProvider>
            <div className="flex flex-col gap-6" data-quill>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <ImportWizardStepper steps={STEPS} currentStep={step} onStepClick={setStep} />
                    {step !== ImportWizardStep.Source && (
                        <Button
                            variant="default"
                            size="icon"
                            aria-label="Start over"
                            tooltip="Start over"
                            onClick={resetWizard}
                            data-attr="error-tracking-import-start-over"
                        >
                            <IconX />
                        </Button>
                    )}
                </div>
                {/* The preview lists long filter patterns, so the last step gets more room than the forms. */}
                <div
                    className={cn(
                        'mx-auto flex w-full flex-col gap-4',
                        step === ImportWizardStep.Import ? 'max-w-3xl' : 'max-w-lg'
                    )}
                >
                    {step === ImportWizardStep.Source ? (
                        <ImportSourceStep />
                    ) : step === ImportWizardStep.Location ? (
                        <SentryLocationStep />
                    ) : step === ImportWizardStep.Token ? (
                        <SentryTokenStep />
                    ) : (
                        <SentryImportStep />
                    )}
                </div>
            </div>
        </TooltipProvider>
    )
}
