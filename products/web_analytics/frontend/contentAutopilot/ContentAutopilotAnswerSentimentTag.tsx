import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { percentage } from 'lib/utils/numbers'

import { AiVisibilityTag } from './AiVisibilityTag'
import { SENTIMENT_LABELS } from './answerSentiment'

const TAG_TYPES: Record<string, LemonTagType> = { positive: 'success', negative: 'danger' }

/** How one answer speaks about our brand. Says so when the answer names the brand but is not scored yet, and
 *  renders nothing for an answer that never names it, because there is nothing to score. */
export const ContentAutopilotAnswerSentimentTag = ({
    sentiment,
    score,
    namesBrand,
}: {
    sentiment: string | null
    score: number | null
    namesBrand: boolean
}): JSX.Element | null => {
    if (!sentiment) {
        return namesBrand ? (
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>
                    <AiVisibilityTag type="muted" data-attr="content-autopilot-prompt-answer-sentiment">
                        Sentiment not scored yet
                    </AiVisibilityTag>
                </TooltipTrigger>
                <TooltipContent>Answers that mention you are scored a few minutes after each check.</TooltipContent>
            </Tooltip>
        ) : null
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>
                <AiVisibilityTag
                    type={TAG_TYPES[sentiment] ?? 'default'}
                    data-attr="content-autopilot-prompt-answer-sentiment"
                >
                    {SENTIMENT_LABELS[sentiment] ?? sentiment} about you
                    {score !== null ? ` (${percentage(score, 0)} confidence)` : ''}
                </AiVisibilityTag>
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
                Sentiment of the sentences that mention you, averaged. Hover a highlighted sentence to see its own.
            </TooltipContent>
        </Tooltip>
    )
}
