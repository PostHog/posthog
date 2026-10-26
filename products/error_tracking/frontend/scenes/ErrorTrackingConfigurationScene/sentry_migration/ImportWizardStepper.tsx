import { Fragment } from 'react'

import { Badge, Button, Separator } from '@posthog/quill'

export interface ImportWizardStepperStep<Key extends string> {
    key: Key
    label: string
}

export interface ImportWizardStepperProps<Key extends string> {
    steps: ImportWizardStepperStep<Key>[]
    currentStep: Key
    onStepClick: (step: Key) => void
}

export function ImportWizardStepper<Key extends string>({
    steps,
    currentStep,
    onStepClick,
}: ImportWizardStepperProps<Key>): JSX.Element {
    const currentIndex = steps.findIndex((step) => step.key === currentStep)

    return (
        <nav aria-label="Import progress" className="flex flex-wrap items-center justify-center gap-1">
            {steps.map((step, index) => (
                <Fragment key={step.key}>
                    {index > 0 && <Separator className="w-4" />}
                    <Button
                        variant="default"
                        aria-current={index === currentIndex ? 'step' : undefined}
                        disabledReason={index > currentIndex ? 'Finish the earlier steps first' : undefined}
                        onClick={() => onStepClick(step.key)}
                    >
                        <Badge variant={index < currentIndex ? 'success' : index === currentIndex ? 'info' : 'default'}>
                            {index + 1}
                        </Badge>
                        {step.label}
                    </Button>
                </Fragment>
            ))}
        </nav>
    )
}
