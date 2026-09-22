import './OnboardingTakeover.scss'

import { type ReactNode, useCallback } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogTitle,
    Dot,
    Heading,
    Text,
} from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import { OnboardingMediaPanel } from './OnboardingStepMedia'
import type { OnboardingStep, OnboardingStepKey } from './onboardingSteps'

// Logic-free onboarding dialog that walks one step at a time. The caller owns the step index, what
// "dismiss" persists, and the interactive blocks for the steps that need live state (the GitHub CTA on
// CONNECT, the starter prompts on START) — this component only presents.

export interface OnboardingTakeoverProps {
    open: boolean
    steps: readonly OnboardingStep[]
    stepIndex: number
    onStepIndexChange: (stepIndex: number) => void
    /** Rendered under the body copy of the matching step. The one seam for steps that read live state. */
    stepActions?: Partial<Record<OnboardingStepKey, ReactNode>>
    /** Fires on the close button, Esc, and the backdrop. */
    onDismiss: () => void
    /** Fires when the user advances past the last step. */
    onFinish: () => void
    /** Fires when the user replays a step's clip by hand (only reachable when motion is reduced). */
    onReplayMedia?: (step: OnboardingStep) => void
}

export function OnboardingTakeover({
    open,
    steps,
    stepIndex,
    onStepIndexChange,
    stepActions,
    onDismiss,
    onFinish,
    onReplayMedia,
}: OnboardingTakeoverProps): JSX.Element | null {
    const step = steps[stepIndex]
    const isFirstStep = stepIndex === 0
    const isLastStep = stepIndex === steps.length - 1

    const handleOpenChange = useCallback(
        (nextOpen: boolean): void => {
            if (!nextOpen) {
                onDismiss()
            }
        },
        [onDismiss]
    )

    const handleNext = useCallback((): void => {
        if (isLastStep) {
            onFinish()
        } else {
            onStepIndexChange(stepIndex + 1)
        }
    }, [isLastStep, onFinish, onStepIndexChange, stepIndex])

    if (!step) {
        return null
    }

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent
                className="PhaiOnboardingTakeover"
                data-attr="posthog-ai-onboarding"
                aria-label="What's new in PostHog AI"
            >
                {/* No DialogHeader: the media panel leads, so the headline sits below it inside the body
                    rather than in a pinned row above. */}
                <DialogBody>
                    <div className="flex w-full flex-col gap-4">
                        <OnboardingMediaPanel
                            steps={steps}
                            stepIndex={stepIndex}
                            open={open}
                            onReplay={onReplayMedia}
                        />
                        <DialogTitle render={<Heading size="lg" />}>{step.headline}</DialogTitle>
                        <Text size="sm" variant="muted">
                            {step.body}
                        </Text>
                        {stepActions?.[step.key]}
                    </div>
                </DialogBody>

                {/* A three-column grid, not `justify-between`: the left group is wider than the right, so
                    space-between would push the step dots off the dialog's centerline. Also keeps the bar a
                    single row, where quill's footer would stack it in reverse order below `sm`. */}
                <DialogFooter className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                    <div className="justify-self-start">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onStepIndexChange(stepIndex - 1)}
                            disabled={isFirstStep}
                            data-attr="posthog-ai-onboarding-back"
                        >
                            Back
                        </Button>
                    </div>

                    {/* Plain buttons, not a tablist: there are no tab panels here, only a step the whole
                        dialog swaps to, so `aria-current` describes it honestly. Each button's only child
                        is a decorative Dot, so the headline has to supply the accessible name. */}
                    <div className="flex items-center gap-1.5">
                        {steps.map((indicatorStep, index) => (
                            <button
                                key={indicatorStep.key}
                                type="button"
                                aria-current={index === stepIndex ? 'step' : undefined}
                                aria-label={indicatorStep.headline}
                                className="flex items-center p-1"
                                onClick={() => onStepIndexChange(index)}
                                data-attr={`posthog-ai-onboarding-step-${indicatorStep.key}`}
                            >
                                <Dot
                                    variant={index === stepIndex ? 'info' : 'default'}
                                    className={cn(index !== stepIndex && 'opacity-40')}
                                />
                            </button>
                        ))}
                    </div>

                    {/* The last step's action block carries the call to action, so there's no Next to show.
                        The grid cell stays either way, so the dots do not shift on the final step. */}
                    <div className="justify-self-end">
                        {!isLastStep && (
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={handleNext}
                                data-attr="posthog-ai-onboarding-next"
                            >
                                Next
                            </Button>
                        )}
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
