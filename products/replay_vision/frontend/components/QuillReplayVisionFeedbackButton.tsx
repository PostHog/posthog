import { LemonButtonProps } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import posthog from 'lib/posthog-typed'

export function QuillReplayVisionFeedbackButton({
    label = 'Feedback',
    type,
}: {
    label?: string
    type?: LemonButtonProps['type']
} = {}): JSX.Element {
    return (
        <Button
            data-attr="vision-feedback"
            variant={quillButtonVariant(type)}
            tooltip="Share feedback on Replay vision"
            onClick={() => posthog.capture('replay_vision_feedback_clicked')}
        >
            {label}
        </Button>
    )
}
