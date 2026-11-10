import { useActions } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { aiOnboardingLogic } from '../../logics/aiOnboardingLogic'

export interface QuillOnboardingReplayButtonProps {
    panelId?: string
    className?: string
}

/**
 * Quill skin of `OnboardingReplayButton`: an icon-only trigger for the composer toolbar. Temporary for the same
 * reason, so delete it with that component once the migration to the new PostHog AI is done.
 */
export function QuillOnboardingReplayButton({ panelId, className }: QuillOnboardingReplayButtonProps): JSX.Element {
    const { openOnboarding } = useActions(aiOnboardingLogic({ panelId }))

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label="What's new in PostHog AI"
                        onClick={() => openOnboarding(true)}
                        className={className}
                        data-attr="posthog-ai-onboarding-replay"
                    >
                        <IconInfo />
                    </Button>
                }
            />
            <TooltipContent>What's new in PostHog AI</TooltipContent>
        </Tooltip>
    )
}
