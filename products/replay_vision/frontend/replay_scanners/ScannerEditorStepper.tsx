import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { SCANNER_EDITOR_STEP_ORDER, STEP_LABELS, ScannerEditorStep } from './scannerEditorSceneLogic'

interface ScannerEditorStepperProps {
    currentStep: ScannerEditorStep
    steps: readonly ScannerEditorStep[]
    onStepClick: (step: ScannerEditorStep) => void
    stepErrors?: Partial<Record<ScannerEditorStep, boolean>>
    /** Steps that stay in the sequence for consistent numbering but can't be navigated to. */
    disabledSteps?: Partial<Record<ScannerEditorStep, string>>
}

export function ScannerEditorStepper({
    currentStep,
    steps,
    onStepClick,
    stepErrors = {},
    disabledSteps = {},
}: ScannerEditorStepperProps): JSX.Element {
    const currentOrder = SCANNER_EDITOR_STEP_ORDER[currentStep]

    return (
        <nav className="flex flex-wrap items-center justify-center gap-y-1" aria-label="Scanner editor progress">
            {steps.map((stepKey, index) => {
                const step = { key: stepKey, label: STEP_LABELS[stepKey] }
                const stepOrder = SCANNER_EDITOR_STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key
                const hasErrors = !!stepErrors[step.key]
                const disabledReason = disabledSteps[step.key]

                return (
                    <div key={step.key} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    hasErrors
                                        ? 'bg-warning'
                                        : isCompleted || isCurrent
                                          ? 'bg-success'
                                          : 'bg-border-primary'
                                )}
                            />
                        )}
                        <Tooltip title={disabledReason}>
                            <button
                                type="button"
                                onClick={() => !disabledReason && onStepClick(step.key)}
                                aria-disabled={!!disabledReason}
                                data-attr={`vision-editor-step-${step.key}`}
                                className={cn(
                                    'group flex items-center gap-1.5 px-2 py-1 rounded transition-all duration-150',
                                    'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                    disabledReason
                                        ? 'opacity-50 cursor-default'
                                        : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                                )}
                                aria-current={isCurrent ? 'step' : undefined}
                            >
                                {/* Errors outrank the completed checkmark. */}
                                {hasErrors ? (
                                    <Tooltip title="This step has errors to fix">
                                        <IconWarning className="size-5 text-warning" />
                                    </Tooltip>
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
                        </Tooltip>
                    </div>
                )
            })}
        </nav>
    )
}
