import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { BROADCAST_WIZARD_STEPS, BroadcastWizardStep } from './broadcastWizardLogic'

const STEP_LABELS: Record<BroadcastWizardStep, string> = {
    recipients: 'Recipients',
    goal: 'Goal',
    content: 'Content',
    schedule: 'Schedule',
    review: 'Review',
}

interface BroadcastWizardStepperProps {
    currentStep: BroadcastWizardStep
    onStepClick: (step: BroadcastWizardStep) => void
    stepErrors?: Partial<Record<BroadcastWizardStep, string[]>>
}

export function BroadcastWizardStepper({
    currentStep,
    onStepClick,
    stepErrors = {},
}: BroadcastWizardStepperProps): JSX.Element {
    const currentOrder = BROADCAST_WIZARD_STEPS.indexOf(currentStep)
    const currentStepHasErrors = (stepErrors[currentStep]?.length ?? 0) > 0

    const handleStepClick = (step: BroadcastWizardStep): void => {
        // Block forward navigation while the current step has errors; going back is always fine.
        const targetOrder = BROADCAST_WIZARD_STEPS.indexOf(step)
        if (currentStepHasErrors && targetOrder > currentOrder) {
            return
        }
        onStepClick(step)
    }

    return (
        <nav className="flex items-center" aria-label="Broadcast wizard progress">
            {BROADCAST_WIZARD_STEPS.map((step, index) => {
                const isCompleted = currentOrder > index
                const isCurrent = currentStep === step
                const hasErrors = (stepErrors[step]?.length ?? 0) > 0
                const isBlocked = currentStepHasErrors && index > currentOrder

                const button = (
                    <button
                        type="button"
                        onClick={() => handleStepClick(step)}
                        disabled={isBlocked}
                        className={cn(
                            'group flex items-center gap-1.5 px-2 py-1 rounded',
                            'transition-all duration-150',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            isBlocked
                                ? 'opacity-50 cursor-not-allowed'
                                : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                        )}
                        aria-current={isCurrent ? 'step' : undefined}
                        data-attr={`broadcast-wizard-step-${step}`}
                    >
                        {hasErrors && isCurrent ? (
                            <IconWarning className="size-5 text-warning" />
                        ) : isCompleted ? (
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
                            {STEP_LABELS[step]}
                        </span>
                    </button>
                )

                return (
                    <div key={step} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    hasErrors && isCurrent
                                        ? 'bg-warning'
                                        : isCompleted || isCurrent
                                          ? 'bg-success'
                                          : 'bg-border-primary'
                                )}
                            />
                        )}
                        {isBlocked ? <Tooltip title="Fix errors before proceeding">{button}</Tooltip> : button}
                    </div>
                )
            })}
        </nav>
    )
}
