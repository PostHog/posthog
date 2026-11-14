import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import posthog from 'lib/posthog-typed'

const FEEDBACK_TOOLTIP = 'Share feedback on the self-driving inbox'
// pinned: the feedback survey triggers on this event name. Renaming it stops the survey.
const FEEDBACK_EVENT = 'self_driving_feedback_clicked'
// pinned: autocapture selector.
const FEEDBACK_DATA_ATTR = 'inbox-feedback'

/**
 * Feedback button for the scene header. Clicking it captures `self_driving_feedback_clicked`, which
 * triggers the Self-driving feedback survey (a popover) configured in PostHog.
 */
export function InboxFeedbackButton(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const onClick = (): void => {
        posthog.capture(FEEDBACK_EVENT)
    }

    if (todayRailNav) {
        return (
            <Button variant="outline" tooltip={FEEDBACK_TOOLTIP} onClick={onClick} data-attr={FEEDBACK_DATA_ATTR}>
                Feedback
            </Button>
        )
    }
    return (
        <LemonButton
            type="secondary"
            size="small"
            tooltip={FEEDBACK_TOOLTIP}
            onClick={onClick}
            data-attr={FEEDBACK_DATA_ATTR}
        >
            Feedback
        </LemonButton>
    )
}
