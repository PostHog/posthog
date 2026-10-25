import { useValues } from 'kea'
import { useContext } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { ChatMessageFooter, cn } from '@posthog/quill-primitives'

import { stripMarkdown } from 'lib/utils/markdown'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import type { TurnFeedbackActionsProps } from '../turnFeedbackTypes'
import { TurnRevealContext } from '../TurnRevealContext'
import { useTurnRating } from '../useTurnRating'
import { footerRevealClass } from './footerReveal'
import { QuillCopyButton, QuillFooterButton } from './QuillFooterButton'
import { QuillFooterTimestamp } from './QuillFooterTimestamp'
import { QuillTurnFeedbackDialog } from './QuillTurnFeedbackDialog'

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
    const { rating, submitRating, isFeedbackDialogOpen, closeFeedbackDialog } = useTurnRating({
        sessionId,
        turnIndex,
        run,
        traceId,
    })

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
                        label={rating === 'good' ? 'Rated as a good answer' : 'Good answer'}
                        dataAttr="posthog-ai-turn-rating-good"
                        onClick={() => submitRating('good')}
                    >
                        {rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    </QuillFooterButton>
                )}
                {rating !== 'good' && (
                    <QuillFooterButton
                        label={rating === 'bad' ? 'Rated as a bad answer' : 'Bad answer'}
                        dataAttr="posthog-ai-turn-rating-bad"
                        onClick={() => submitRating('bad')}
                    >
                        {rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    </QuillFooterButton>
                )}
            </ChatMessageFooter>
            <QuillTurnFeedbackDialog isOpen={isFeedbackDialogOpen} onClose={closeFeedbackDialog} />
        </div>
    )
}
