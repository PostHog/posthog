import { Fragment } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

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
    // A long wizard shows only the current label until its container is wide enough for all of them.
    const compact = steps.length > 5

    return (
        <nav className="flex flex-wrap items-center justify-center" aria-label="Import progress">
            {steps.map((step, index) => {
                const isCompleted = index < currentIndex
                const isCurrent = index === currentIndex
                const isFuture = index > currentIndex
                const button = (
                    <button
                        type="button"
                        onClick={() => onStepClick(step.key)}
                        disabled={isFuture}
                        aria-label={step.label}
                        aria-current={isCurrent ? 'step' : undefined}
                        className={cn(
                            'flex items-center gap-1.5 px-2 py-1 rounded',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            isFuture ? 'opacity-50 cursor-not-allowed' : 'hover:bg-fill-button-tertiary-hover'
                        )}
                    >
                        {isCompleted ? (
                            <IconCheckCircle className="size-5 text-success" />
                        ) : (
                            <span
                                className={cn(
                                    'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                    isCurrent
                                        ? 'bg-accent text-primary-inverse'
                                        : 'bg-surface-secondary text-secondary border border-primary'
                                )}
                            >
                                {index + 1}
                            </span>
                        )}
                        <span
                            className={cn(
                                'text-sm',
                                isCurrent && 'font-semibold text-primary',
                                isCompleted && 'font-medium text-primary',
                                !isCompleted && !isCurrent && 'text-secondary',
                                compact && !isCurrent && 'hidden @5xl:inline'
                            )}
                        >
                            {step.label}
                        </span>
                    </button>
                )
                return (
                    <Fragment key={step.key}>
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px',
                                    isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}
                        {compact && !isCurrent ? <Tooltip title={step.label}>{button}</Tooltip> : button}
                    </Fragment>
                )
            })}
        </nav>
    )
}
