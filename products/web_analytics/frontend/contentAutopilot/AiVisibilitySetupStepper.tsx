import { Fragment } from 'react'

import { IconCheck, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { SetupWizardStep } from './contentAutopilotSetupLogic'

export interface AiVisibilitySetupStepDefinition {
    step: SetupWizardStep
    label: string
    dataAttr: string
}

/** The setup wizard's steps in order. A step before the current one shows a check, and a blocked one says why. */
export const AiVisibilitySetupStepper = ({
    steps,
    currentStep,
    onStepClick,
    disabledSteps,
}: {
    steps: AiVisibilitySetupStepDefinition[]
    currentStep: SetupWizardStep
    onStepClick: (step: SetupWizardStep) => void
    disabledSteps: Partial<Record<SetupWizardStep, string>>
}): JSX.Element => {
    const currentIndex = steps.findIndex(({ step }) => step === currentStep)
    return (
        <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0" aria-label="AI visibility setup">
            {steps.map(({ step, label, dataAttr }, index) => (
                <Fragment key={step}>
                    {index > 0 ? (
                        <li aria-hidden className="flex text-muted-foreground">
                            <IconChevronRight />
                        </li>
                    ) : null}
                    <li>
                        <Button
                            variant={index === currentIndex ? 'outline' : 'default'}
                            size="sm"
                            onClick={() => onStepClick(step)}
                            disabledReason={disabledSteps[step]}
                            aria-current={index === currentIndex ? 'step' : undefined}
                            data-attr={dataAttr}
                        >
                            <span className="flex size-4 items-center justify-center tabular-nums">
                                {index < currentIndex ? <IconCheck className="text-success-foreground" /> : index + 1}
                            </span>
                            {label}
                        </Button>
                    </li>
                </Fragment>
            ))}
        </ol>
    )
}
