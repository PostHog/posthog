import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { SCANNER_EDITOR_STEP_ORDER, ScannerEditorStep } from './scannerEditorSceneLogic'

const STEP_LABELS: Record<ScannerEditorStep, string> = {
    template: 'Template',
    configure: 'Configure',
    triggers: 'Triggers',
}

interface ScannerEditorStepperProps {
    currentStep: ScannerEditorStep
    steps: readonly ScannerEditorStep[]
    onStepClick: (step: ScannerEditorStep) => void
    stepErrors?: Partial<Record<ScannerEditorStep, boolean>>
}

export function ScannerEditorStepper({
    currentStep,
    steps,
    onStepClick,
    stepErrors = {},
}: ScannerEditorStepperProps): JSX.Element {
    const currentOrder = SCANNER_EDITOR_STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center justify-center" aria-label="Scanner editor progress">
            {steps.map((stepKey, index) => {
                const step = { key: stepKey, label: STEP_LABELS[stepKey] }
                const stepOrder = SCANNER_EDITOR_STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key
                const hasErrors = !!stepErrors[step.key]

                return (
                    <div key={step.key} className="flex items-center">
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
                        <button
                            type="button"
                            onClick={() => onStepClick(step.key)}
                            data-attr={`vision-editor-step-${step.key}`}
                            // The current step is a no-op; drop the interactive affordances so it doesn't read as a dead click.
                            aria-disabled={isCurrent || undefined}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded transition-all duration-150',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                isCurrent ? 'cursor-default' : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                            )}
                            aria-current={isCurrent ? 'step' : undefined}
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
                                {step.label}
                            </span>
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}
