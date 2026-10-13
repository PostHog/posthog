import { IconCheckCircle } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { WIZARD_STEP_COPY, WizardStepKey } from './onboardingWizardSteps'

interface OnboardingWizardStepperProps {
    steps: readonly WizardStepKey[]
    currentIndex: number
    stepDone: Partial<Record<WizardStepKey, boolean>> | null
    onStepClick: (index: number) => void
}

/** The wizard progress. Earlier steps stay clickable, so a person can go back without losing their place. */
export function OnboardingWizardStepper({
    steps,
    currentIndex,
    stepDone,
    onStepClick,
}: OnboardingWizardStepperProps): JSX.Element {
    return (
        <nav className="flex flex-wrap items-center justify-center gap-y-2" aria-label="Setup progress">
            {steps.map((step, index) => {
                const isCurrent = index === currentIndex
                const isDone = !!stepDone?.[step]
                const canVisit = index < currentIndex
                return (
                    <div key={step} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn('w-6 h-px', index <= currentIndex ? 'bg-success' : 'bg-border-primary')}
                            />
                        )}
                        <button
                            type="button"
                            onClick={() => onStepClick(index)}
                            disabled={!canVisit}
                            aria-current={isCurrent ? 'step' : undefined}
                            className={cn(
                                'flex items-center gap-1.5 px-2 py-1 rounded',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                canVisit ? 'hover:bg-fill-button-tertiary-hover' : 'cursor-default'
                            )}
                            data-attr={`workflows-onboarding-wizard-stepper-${step}`}
                        >
                            {isDone && !isCurrent ? (
                                <IconCheckCircle className="size-5 text-success" />
                            ) : (
                                <span
                                    className={cn(
                                        'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                        isCurrent
                                            ? 'bg-accent text-primary-inverse ring-2 ring-accent/25'
                                            : 'bg-surface-secondary text-secondary border border-primary'
                                    )}
                                >
                                    {index + 1}
                                </span>
                            )}
                            <span
                                className={cn(
                                    'text-sm',
                                    isCurrent
                                        ? 'font-semibold text-primary'
                                        : isDone
                                          ? 'text-primary'
                                          : 'text-secondary'
                                )}
                            >
                                {WIZARD_STEP_COPY[step].label}
                            </span>
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}
