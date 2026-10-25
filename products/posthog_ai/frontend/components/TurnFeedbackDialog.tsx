import { useId, useState } from 'react'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { FeedbackDialogOutcome } from '../utils/feedbackEvents'

export interface TurnFeedbackDialogProps {
    isOpen: boolean
    onClose: (outcome: FeedbackDialogOutcome, text: string) => void
}

/** The "Share feedback" dialog a thumbs-down opens. Submitting works with an empty text area. */
export function TurnFeedbackDialog({ isOpen, onClose }: TurnFeedbackDialogProps): JSX.Element {
    const [feedback, setFeedback] = useState('')
    const textAreaId = useId()

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => onClose('cancelled', feedback)}
            title="Share feedback"
            width={480}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="posthog-ai-turn-feedback-cancel"
                        onClick={() => onClose('cancelled', feedback)}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="posthog-ai-turn-feedback-submit"
                        onClick={() => onClose('submitted', feedback)}
                    >
                        Submit
                    </LemonButton>
                </>
            }
        >
            <LemonField.Pure label="What disappointed you about the answer?" showOptional htmlFor={textAreaId}>
                <LemonTextArea
                    id={textAreaId}
                    placeholder="Help us improve PostHog AI…"
                    value={feedback}
                    onChange={setFeedback}
                    onPressCmdEnter={() => onClose('submitted', feedback)}
                    minRows={3}
                    autoFocus
                />
            </LemonField.Pure>
        </LemonModal>
    )
}
