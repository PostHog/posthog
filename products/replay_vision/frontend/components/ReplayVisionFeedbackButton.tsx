import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import posthog from 'lib/posthog-typed'

import { QuillReplayVisionFeedbackButton } from './QuillReplayVisionFeedbackButton'

/**
 * Feedback button for the Replay vision product. Clicking it captures the `replay_vision_feedback_clicked`
 * event, which triggers the Replay vision feedback survey (a popover) configured in PostHog.
 */
export function ReplayVisionFeedbackButton({
    label = 'Feedback',
    type,
}: {
    label?: string
    type?: LemonButtonProps['type']
} = {}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return <QuillReplayVisionFeedbackButton label={label} type={type} />
    }
    return (
        <LemonButton
            data-attr="vision-feedback"
            size="small"
            type={type}
            tooltip="Share feedback on Replay vision"
            onClick={() => posthog.capture('replay_vision_feedback_clicked')}
        >
            {label}
        </LemonButton>
    )
}
