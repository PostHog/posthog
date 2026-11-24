import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { QuillImportSourceStep } from './QuillImportSourceStep'
import { QuillImportWizardStepper } from './QuillImportWizardStepper'
import { QuillSentryCategoryStep } from './QuillSentryCategoryStep'
import { QuillSentryLocationStep } from './QuillSentryLocationStep'
import { QuillSentryProjectStep } from './QuillSentryProjectStep'
import { QuillSentryReviewStep } from './QuillSentryReviewStep'
import { QuillSentryTokenStep } from './QuillSentryTokenStep'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { FORM_STEPS, IMPORT_CATEGORIES, ImportWizardStep } from './sentryMigrationSteps'

export function QuillImportWizard(): JSX.Element {
    const { step, steps } = useValues(sentryMigrationLogic)
    const { setStep, resetWizard } = useActions(sentryMigrationLogic)
    const category = IMPORT_CATEGORIES.find((importCategory) => importCategory.step === step)

    return (
        <div className="@container flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <QuillImportWizardStepper steps={steps} currentStep={step} onStepClick={setStep} />
                {step !== ImportWizardStep.Source && (
                    <Button
                        size="icon"
                        onClick={resetWizard}
                        aria-label="Start over"
                        tooltip="Start over"
                        data-attr="error-tracking-import-start-over"
                    >
                        <IconX />
                    </Button>
                )}
            </div>
            <div className={cn('flex w-full flex-col gap-3', FORM_STEPS.includes(step) ? 'max-w-lg' : 'max-w-3xl')}>
                {step === ImportWizardStep.Source ? (
                    <QuillImportSourceStep />
                ) : step === ImportWizardStep.Location ? (
                    <QuillSentryLocationStep />
                ) : step === ImportWizardStep.Token ? (
                    <QuillSentryTokenStep />
                ) : step === ImportWizardStep.Project ? (
                    <QuillSentryProjectStep />
                ) : category ? (
                    <QuillSentryCategoryStep category={category} />
                ) : (
                    <QuillSentryReviewStep />
                )}
            </div>
        </div>
    )
}
