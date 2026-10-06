import clsx from 'clsx'
import { useContext, memo } from 'react'

import { IconCopy, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { stripMarkdown } from 'lib/utils/markdown'

import { MessageTemplate } from '../messages/MessageTemplate'
import { useQuillThread } from './quill/quillThreadContext'
import { QuillTurnFeedbackActions } from './quill/QuillTurnFeedbackActions'
import type { TurnFeedbackActionsProps } from './turnFeedbackTypes'
import { TurnRevealContext } from './TurnRevealContext'
import { useTurnRating } from './useTurnRating'

/**
 * Feedback actions under a completed turn: copy, thumbs up/down, the completion time, and a
 * free-text form on thumbs-down. Counterpart of the legacy thread's `SuccessActions` — same events
 * (`$ai_metric` quality / `$ai_feedback`), plus runtime/task/run properties.
 */
export const TurnFeedbackActions = memo(function TurnFeedbackActions(props: TurnFeedbackActionsProps): JSX.Element {
    return useQuillThread() ? <QuillTurnFeedbackActions {...props} /> : <LemonTurnFeedbackActions {...props} />
})

function LemonTurnFeedbackActions({
    sessionId,
    turnIndex,
    run,
    traceId,
    turnText,
    timestamp,
}: TurnFeedbackActionsProps): JSX.Element {
    const turnHovered = useContext(TurnRevealContext)
    const { rating, submitRating, feedback, setFeedback, feedbackInputStatus, closeFeedback, submitFeedback } =
        useTurnRating({ sessionId, turnIndex, run, traceId })

    return (
        <>
            <div className="group flex items-center ml-1">
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
                {timestamp !== undefined && (
                    <TZLabel
                        time={new Date(timestamp).toISOString()}
                        className={clsx(
                            'text-xs text-muted ml-1 transition-opacity group-focus-within:opacity-100',
                            !turnHovered && 'opacity-0'
                        )}
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
                        <LemonButton icon={<IconX />} type="tertiary" size="xsmall" onClick={closeFeedback} />
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
}
