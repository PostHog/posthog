import { IconCheck } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { ImportWizardStepperProps } from './ImportWizardStepper'

export function QuillImportWizardStepper<Key extends string>({
    steps,
    currentStep,
    onStepClick,
}: ImportWizardStepperProps<Key>): JSX.Element {
    const currentIndex = steps.findIndex((step) => step.key === currentStep)
    // A long wizard shows only the current label until its container is wide enough for all of them.
    const compact = steps.length > 5

    return (
        <nav aria-label="Import progress">
            <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0">
                {steps.map((step, index) => {
                    const isCompleted = index < currentIndex
                    const isCurrent = index === currentIndex
                    const hideLabel = compact && !isCurrent

                    return (
                        <li key={step.key} className="flex min-w-0 items-center gap-1">
                            <Button
                                variant={isCurrent ? 'primary' : 'default'}
                                onClick={() => onStepClick(step.key)}
                                disabledReason={index > currentIndex ? 'Finish the earlier steps first' : undefined}
                                tooltip={hideLabel ? step.label : undefined}
                                aria-label={step.label}
                                aria-current={isCurrent ? 'step' : undefined}
                            >
                                {isCompleted ? (
                                    <IconCheck className="text-success-foreground" />
                                ) : (
                                    <span className="tabular-nums">{index + 1}</span>
                                )}
                                <span className={hideLabel ? 'hidden @5xl:inline' : 'truncate'}>{step.label}</span>
                            </Button>
                            {index < steps.length - 1 ? (
                                <span className="text-subtle-foreground" aria-hidden>
                                    →
                                </span>
                            ) : null}
                        </li>
                    )
                })}
            </ol>
        </nav>
    )
}
