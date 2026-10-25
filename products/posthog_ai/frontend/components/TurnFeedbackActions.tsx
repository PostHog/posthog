import clsx from 'clsx'
import { useContext, memo } from 'react'

import { IconCopy, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { stripMarkdown } from 'lib/utils/markdown'

import { useQuillThread } from './quill/quillThreadContext'
import { QuillTurnFeedbackActions } from './quill/QuillTurnFeedbackActions'
import { TurnFeedbackDialog } from './TurnFeedbackDialog'
import type { TurnFeedbackActionsProps } from './turnFeedbackTypes'
import { TurnRevealContext } from './TurnRevealContext'
import { useTurnRating } from './useTurnRating'

/**
 * Feedback actions under a completed turn: copy, thumbs up/down, the completion time, and the
 * feedback dialog a thumbs-down opens. Counterpart of the legacy thread's `SuccessActions` — same events
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
    const { rating, submitRating, isFeedbackDialogOpen, closeFeedbackDialog } = useTurnRating({
        sessionId,
        turnIndex,
        run,
        traceId,
    })

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
                        tooltip={rating === 'good' ? 'Rated as a good answer' : 'Good answer'}
                        data-attr="posthog-ai-turn-rating-good"
                        onClick={() => submitRating('good')}
                    />
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        tooltip={rating === 'bad' ? 'Rated as a bad answer' : 'Bad answer'}
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
            <TurnFeedbackDialog isOpen={isFeedbackDialogOpen} onClose={closeFeedbackDialog} />
        </>
    )
}
