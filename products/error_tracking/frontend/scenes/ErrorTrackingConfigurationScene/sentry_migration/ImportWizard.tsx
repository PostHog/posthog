import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ImportSourceStep } from './ImportSourceStep'
import { ImportWizardStepper } from './ImportWizardStepper'
import { SentryCategoryStep } from './SentryCategoryStep'
import { SentryLocationStep } from './SentryLocationStep'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { IMPORT_CATEGORIES, ImportWizardStep } from './sentryMigrationSteps'
import { SentryProjectStep } from './SentryProjectStep'
import { SentryReviewStep } from './SentryReviewStep'
import { SentryTokenStep } from './SentryTokenStep'

const FORM_STEPS = [ImportWizardStep.Source, ImportWizardStep.Location, ImportWizardStep.Token]

export function ImportWizard(): JSX.Element {
    const { step, steps } = useValues(sentryMigrationLogic)
    const { setStep, resetWizard } = useActions(sentryMigrationLogic)
    const category = IMPORT_CATEGORIES.find((importCategory) => importCategory.step === step)

    return (
        <div className="@container flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-center gap-2">
                <ImportWizardStepper steps={steps} currentStep={step} onStepClick={setStep} />
                {step !== ImportWizardStep.Source && (
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        tooltip="Start over"
                        aria-label="Start over"
                        onClick={resetWizard}
                        data-attr="error-tracking-import-start-over"
                    />
                )}
            </div>
            {/* The project and import steps list long filter patterns, so they get more room than the forms. */}
            <div
                className={cn(
                    'mx-auto flex w-full flex-col gap-4',
                    FORM_STEPS.includes(step) ? 'max-w-lg' : 'max-w-3xl'
                )}
            >
                {step === ImportWizardStep.Source ? (
                    <ImportSourceStep />
                ) : step === ImportWizardStep.Location ? (
                    <SentryLocationStep />
                ) : step === ImportWizardStep.Token ? (
                    <SentryTokenStep />
                ) : step === ImportWizardStep.Project ? (
                    <SentryProjectStep />
                ) : category ? (
                    <SentryCategoryStep category={category} />
                ) : (
                    <SentryReviewStep />
                )}
            </div>
        </div>
    )
}
