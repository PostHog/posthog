import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCopy, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { stripMarkdown } from 'lib/utils/markdown'

import { messageRatingsLogic } from '../../logics/messageRatingsLogic'
import { MessageTemplate } from '../../messages/MessageTemplate'

export interface MessageFeedbackActionsProps {
    /** Run-level trace id the rating attaches to; the widget no-ops until it's available. */
    traceId: string | null
    /** Answer text to offer a copy button for; omit to hide it. */
    content?: string | null
}

/** Per-run thumbs up/down with an inline "what disappointed you?" box, sunk to trace-metric telemetry. */
export function MessageFeedbackActions({ traceId, content }: MessageFeedbackActionsProps): JSX.Element {
    const { ratingForTraceId } = useValues(messageRatingsLogic)
    const { setRatingForTraceId } = useActions(messageRatingsLogic)

    const rating = ratingForTraceId(traceId)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating || !traceId) {
            return // Already rated
        }
        setRatingForTraceId({ traceId, rating: newRating })
        posthog.captureTraceMetric(traceId, 'quality', newRating)
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback || !traceId) {
            return // Input is empty
        }
        posthog.captureTraceFeedback(traceId, feedback)
        setFeedbackInputStatus('submitted')
    }

    return (
        <>
            <div className="flex items-center ml-1">
                {content && (
                    <LemonButton
                        icon={<IconCopy />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Copy answer"
                        onClick={() => copyToClipboard(stripMarkdown(content))}
                    />
                )}
                {rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Good answer"
                        onClick={() => submitRating('good')}
                    />
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip="Bad answer"
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
                            onClick={() => {
                                setFeedbackInputStatus('hidden')
                            }}
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
