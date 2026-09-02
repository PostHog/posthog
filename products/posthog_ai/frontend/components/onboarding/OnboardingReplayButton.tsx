import { useActions } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { aiOnboardingLogic } from '../../logics/aiOnboardingLogic'

export interface OnboardingReplayButtonProps {
    /** The composer's panel key, so a starter prompt chosen on replay reaches the right composer. */
    panelId?: string
}

/**
 * Reopens the onboarding takeover. Temporary: this exists for the migration to the new PostHog AI, so
 * people who dismissed the takeover can still find what changed. Delete this component and its call site
 * once the migration is done.
 *
 * Lemon rather than quill: it sits inside the Lemon composer welcome area, and the two libraries must not be
 * mixed within one surface's internals.
 */
export function OnboardingReplayButton({ panelId }: OnboardingReplayButtonProps): JSX.Element {
    const { openOnboarding } = useActions(aiOnboardingLogic({ panelId }))

    return (
        <LemonButton
            type="tertiary"
            size="xsmall"
            icon={<IconInfo />}
            onClick={() => openOnboarding(true)}
            data-attr="posthog-ai-onboarding-replay"
        >
            What's new in PostHog AI
        </LemonButton>
    )
}
