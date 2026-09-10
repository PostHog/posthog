import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconGithub } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { DEFAULT_ONBOARDING_STEPS, DEFAULT_STARTER_PROMPTS } from './onboardingSteps'
import { OnboardingTakeover, type OnboardingTakeoverProps } from './OnboardingTakeover'

// Logic-free and controlled — the story owns the step index, exactly as `AiOnboardingImpl` does. The dialog
// portals to the document body and covers the viewport, so these stories have no surrounding layout.
const meta: Meta<OnboardingTakeoverProps> = {
    title: 'Products/PostHog AI/OnboardingTakeover',
    component: OnboardingTakeover,
    tags: ['autodocs'],
    parameters: { layout: 'fullscreen' },
    render: ({ steps, stepIndex: initialStepIndex, stepActions }) => {
        const [stepIndex, setStepIndex] = useState(initialStepIndex)
        return (
            <OnboardingTakeover
                open
                steps={steps}
                stepIndex={stepIndex}
                onStepIndexChange={setStepIndex}
                stepActions={stepActions}
                onDismiss={() => {}}
                onFinish={() => {}}
            />
        )
    },
}
export default meta

type Story = StoryObj<OnboardingTakeoverProps>

const starterPromptsAction = (
    <div className="flex flex-col gap-2">
        {DEFAULT_STARTER_PROMPTS.map((prompt) => (
            <Button key={prompt} variant="outline" className="h-auto justify-start whitespace-normal py-1.5 text-start">
                {prompt}
            </Button>
        ))}
    </div>
)

/** The opening step, which has to reset what a returning user expects of the old assistant. */
export const FirstStep: Story = {
    args: { steps: DEFAULT_ONBOARDING_STEPS, stepIndex: 0 },
}

/** The GitHub step, the one conversion in the flow. Its action block is supplied by the host. */
export const ConnectStep: Story = {
    args: {
        steps: DEFAULT_ONBOARDING_STEPS,
        stepIndex: DEFAULT_ONBOARDING_STEPS.findIndex((step) => step.key === 'connect'),
        stepActions: {
            connect: (
                <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline">
                        <IconGithub />
                        Connect GitHub
                    </Button>
                </div>
            ),
        },
    },
}

/** The last step. There is no Next button — the starter prompts are the call to action. */
export const StartStep: Story = {
    args: {
        steps: DEFAULT_ONBOARDING_STEPS,
        stepIndex: DEFAULT_ONBOARDING_STEPS.length - 1,
        stepActions: { start: starterPromptsAction },
    },
}

/**
 * A step whose clip has not been recorded yet. Its media panel holds the step's own glyph in exactly the
 * box a clip would occupy, so the dialog is the same size either way. Every default step ships a clip, so
 * this one is synthesized.
 */
export const AwaitingClip: Story = {
    args: {
        steps: DEFAULT_ONBOARDING_STEPS.map((step, index) => (index === 0 ? { ...step, media: undefined } : step)),
        stepIndex: 0,
    },
}
