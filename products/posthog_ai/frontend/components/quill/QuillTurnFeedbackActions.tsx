import { useValues } from 'kea'
import { useContext, useId } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { Button, ChatMessageFooter, Input, Text, cn } from '@posthog/quill-primitives'

import { stripMarkdown } from 'lib/utils/markdown'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import type { TurnFeedbackActionsProps } from '../turnFeedbackTypes'
import { TurnRevealContext } from '../TurnRevealContext'
import { useTurnRating } from '../useTurnRating'
import { footerRevealClass } from './footerReveal'
import { QuillCopyButton, QuillFooterButton } from './QuillFooterButton'
import { QuillFooterTimestamp } from './QuillFooterTimestamp'

export function QuillTurnFeedbackActions({
    sessionId,
    turnIndex,
    run,
    traceId,
    turnText,
    timestamp,
}: TurnFeedbackActionsProps): JSX.Element {
    const turnHovered = useContext(TurnRevealContext)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    const { rating, submitRating, feedback, setFeedback, feedbackInputStatus, closeFeedback, submitFeedback } =
        useTurnRating({ sessionId, turnIndex, run, traceId })
    const feedbackPromptId = useId()

    return (
        <div className="flex flex-col gap-2">
            <ChatMessageFooter
                className={cn(
                    'min-h-5 items-center gap-1 ps-0',
                    footerRevealClass(!!rating || turnHovered || (todayRailEnabled && phoneLayout))
                )}
            >
                {timestamp !== undefined && <QuillFooterTimestamp time={timestamp} />}
                {turnText && (
                    <QuillCopyButton
                        value={stripMarkdown(turnText)}
                        label="Copy answer"
                        dataAttr="posthog-ai-turn-copy"
                    />
                )}
                {rating !== 'bad' && (
                    <QuillFooterButton
                        label="Good answer"
                        dataAttr="posthog-ai-turn-rating-good"
                        onClick={() => submitRating('good')}
                    >
                        {rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    </QuillFooterButton>
                )}
                {rating !== 'good' && (
                    <QuillFooterButton
                        label="Bad answer"
                        dataAttr="posthog-ai-turn-rating-bad"
                        onClick={() => submitRating('bad')}
                    >
                        {rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    </QuillFooterButton>
                )}
            </ChatMessageFooter>
            {feedbackInputStatus !== 'hidden' && (
                <div className="flex max-w-4/5 flex-col gap-2 rounded-lg border border-border p-3">
                    <div className="flex items-center gap-1">
                        <Text id={feedbackPromptId} size="sm" weight="medium" className="grow">
                            {feedbackInputStatus === 'pending'
                                ? 'What disappointed you about the answer?'
                                : 'Thank you for your feedback!'}
                        </Text>
                        <QuillFooterButton label="Close" onClick={closeFeedback}>
                            <IconX />
                        </QuillFooterButton>
                    </div>
                    {feedbackInputStatus === 'pending' && (
                        <form
                            className="flex items-center gap-1.5"
                            onSubmit={(event) => {
                                event.preventDefault()
                                submitFeedback()
                            }}
                        >
                            <Input
                                aria-labelledby={feedbackPromptId}
                                placeholder="Help us improve PostHog AI…"
                                value={feedback}
                                onChange={(event) => setFeedback(event.target.value)}
                                autoFocus
                            />
                            <Button
                                type="submit"
                                variant="primary"
                                data-attr="posthog-ai-turn-feedback-submit"
                                disabled={!feedback}
                            >
                                Submit
                            </Button>
                        </form>
                    )}
                </div>
            )}
        </div>
    )
}
