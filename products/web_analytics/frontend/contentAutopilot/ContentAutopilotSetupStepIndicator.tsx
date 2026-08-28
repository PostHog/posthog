import { IconCheck } from '@posthog/icons'

import type { ContentAutopilotOnboardingStep } from './contentAutopilotLogic'

const STEPS: { key: ContentAutopilotOnboardingStep; label: string }[] = [
    { key: 'site', label: 'Site' },
    { key: 'sources', label: 'Sources' },
    { key: 'delivery', label: 'Delivery' },
]

export const ContentAutopilotSetupStepIndicator = ({
    currentStep,
}: {
    currentStep: ContentAutopilotOnboardingStep
}): JSX.Element => {
    const currentIndex = STEPS.findIndex(({ key }) => key === currentStep)

    return (
        <ol className="flex items-center gap-2 p-0 m-0 list-none" aria-label="Setup progress">
            {STEPS.map((step, index) => (
                <li
                    key={step.key}
                    className="flex items-center gap-2"
                    aria-current={index === currentIndex ? 'step' : undefined}
                >
                    <span
                        className={`flex size-6 items-center justify-center rounded-full text-xs font-medium ${
                            index < currentIndex
                                ? 'bg-success text-white'
                                : index === currentIndex
                                  ? 'bg-primary-3000 text-white'
                                  : 'bg-fill-secondary text-muted'
                        }`}
                    >
                        {index < currentIndex ? <IconCheck className="size-3" /> : index + 1}
                    </span>
                    <span className={index === currentIndex ? 'font-semibold' : 'text-muted'}>{step.label}</span>
                    {index < STEPS.length - 1 ? <span className="h-px w-8 bg-border" aria-hidden /> : null}
                </li>
            ))}
        </ol>
    )
}
