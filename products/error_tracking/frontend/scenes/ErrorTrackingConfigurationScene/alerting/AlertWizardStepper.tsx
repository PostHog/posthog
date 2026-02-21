import { IconCheckCircle } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { WizardStep } from './errorTrackingAlertWizardLogic'

interface Step {
    key: WizardStep
    label: string
}

const STEPS: Step[] = [
    { key: 'destination', label: 'Destination' },
    { key: 'trigger', label: 'Trigger' },
    { key: 'configure', label: 'Configure' },
]

const STEP_ORDER: Record<WizardStep, number> = {
    destination: 0,
    trigger: 1,
    configure: 2,
}

interface AlertWizardStepperProps {
    currentStep: WizardStep
    onStepClick: (step: WizardStep) => void
}

export function AlertWizardStepper({ currentStep, onStepClick }: AlertWizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center justify-center" aria-label="Alert wizard progress">
            {STEPS.map((step, index) => {
                const order = STEP_ORDER[step.key]
                const isCompleted = currentOrder > order
                const isCurrent = currentStep === step.key
                const isFuture = order > currentOrder

                return (
                    <div key={step.key} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}

                        <button
                            type="button"
                            onClick={() => onStepClick(step.key)}
                            disabled={isFuture}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded',
                                'transition-all duration-150',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                isFuture
                                    ? 'opacity-50 cursor-not-allowed'
                                    : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                            )}
                            aria-current={isCurrent ? 'step' : undefined}
                        >
                            {isCompleted ? (
                                <IconCheckCircle className="size-5 text-success" />
                            ) : (
                                <span
                                    className={cn(
                                        'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                        'transition-all duration-150',
                                        isCurrent && 'bg-accent text-primary-inverse ring-2 ring-accent/25',
                                        !isCurrent && 'bg-surface-secondary text-secondary border border-primary'
                                    )}
                                >
                                    {index + 1}
                                </span>
                            )}

                            <span
                                className={cn(
                                    'text-sm transition-colors duration-150',
                                    isCurrent && 'font-semibold text-primary',
                                    isCompleted && 'font-medium text-primary',
                                    !isCompleted && !isCurrent && 'text-secondary'
                                )}
                            >
                                {step.label}
                            </span>
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}
