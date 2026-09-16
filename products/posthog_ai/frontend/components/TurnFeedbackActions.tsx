import { useActions, useValues } from 'kea'
import { useState, memo } from 'react'

import { IconCopy, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { stripMarkdown } from 'lib/utils/markdown'

import { messageRatingsLogic } from '../logics/messageRatingsLogic'
import { MessageTemplate } from '../messages/MessageTemplate'
import { RunRef, captureTurnFeedbackText, captureTurnRating } from '../utils/feedbackEvents'

export interface TurnFeedbackActionsProps {
    /** Task id backing the sandbox conversation. Lands in `$ai_session_id`. */
    sessionId: string
    /** Ordinal of the completed turn — the rating's identity, stable across reloads. */
    turnIndex: number
    run: RunRef
    /** The turn's gateway trace id, when the run reported one. Lands in `$ai_trace_id`. */
    traceId?: string
    turnText: string
}

/**
 * Feedback actions under a completed turn: copy, thumbs up/down, and a free-text form on
 * thumbs-down. Counterpart of the legacy thread's `SuccessActions` — same events
 * (`$ai_metric` quality / `$ai_feedback`), plus runtime/task/run properties.
 */
export const TurnFeedbackActions = memo(function TurnFeedbackActions({
    sessionId,
    turnIndex,
    run,
    traceId,
    turnText,
}: TurnFeedbackActionsProps): JSX.Element {
    const { ratingForKey } = useValues(messageRatingsLogic)
    const { setRating } = useActions(messageRatingsLogic)

    const ratingKey = `${sessionId}:turn-${turnIndex}`
    const rating = ratingForKey(ratingKey)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating) {
            return // Already rated
        }
        setRating({ key: ratingKey, rating: newRating })
        captureTurnRating(sessionId, traceId ?? null, newRating, turnIndex, run)
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback) {
            return // Input is empty
        }
        captureTurnFeedbackText(sessionId, traceId ?? null, feedback, turnIndex, run)
        setFeedbackInputStatus('submitted')
    }

    return (
        <>
            <div className="flex items-center ml-1">
                {turnText && (
                    <LemonButton
                        icon={<IconCopy />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Copy answer"
                        data-attr="posthog-ai-turn-copy"
                        onClick={() => void copyToClipboard(stripMarkdown(turnText))}
                    />
                )}
                {rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Good answer"
                        data-attr="posthog-ai-turn-rating-good"
                        onClick={() => submitRating('good')}
                    />
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Bad answer"
                        data-attr="posthog-ai-turn-rating-bad"
                        onClick={() => submitRating('bad')}
                    />
                )}
            </div>
            {feedbackInputStatus !== 'hidden' && (
                <MessageTemplate type="ai">
                    <div className="flex items-center gap-1">
                        <h4 className="m-0 text-sm grow">
                            {feedbackInputStatus === 'pending'
                                ? 'What disappointed you about the answer?'
                                : 'Thank you for your feedback!'}
                        </h4>
                        <LemonButton
                            icon={<IconX />}
                            type="tertiary"
                            size="xsmall"
                            onClick={() => setFeedbackInputStatus('hidden')}
                        />
                    </div>
                    {feedbackInputStatus === 'pending' && (
                        <div className="flex w-full gap-1.5 items-center mt-1.5">
                            <LemonInput
                                placeholder="Help us improve PostHog AI…"
                                fullWidth
                                value={feedback}
                                onChange={(newValue) => setFeedback(newValue)}
                                onPressEnter={() => submitFeedback()}
                                autoFocus
                            />
                            <LemonButton
                                type="primary"
                                data-attr="posthog-ai-turn-feedback-submit"
                                onClick={() => submitFeedback()}
                                disabledReason={!feedback ? 'Please type a few words!' : undefined}
                            >
                                Submit
                            </LemonButton>
                        </div>
                    )}
                </MessageTemplate>
            )}
        </>
    )
})
