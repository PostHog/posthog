import { memo } from 'react'

import { useFeedbackPrompt } from '../hooks/useFeedbackPrompt'
import { FeedbackPromptLogicProps } from '../logics/feedbackPromptLogic'
import { MessageTemplate } from '../messages/MessageTemplate'
import { FeedbackSessionKind } from '../utils/ticketMetadata'
import { FeedbackPromptDetails } from './FeedbackPromptDetails'
import { FeedbackPromptRating } from './FeedbackPromptRating'

/** The periodic feedback prompt at the bottom of a live thread: rating row, detailed form, or thank-you. */
export const FeedbackPromptTrailer = memo(function FeedbackPromptTrailer({
    sessionId,
    sessionKind,
    streamKey,
}: FeedbackPromptLogicProps & { sessionKind: FeedbackSessionKind }): JSX.Element | null {
    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible, streamingActive } = useFeedbackPrompt(
        sessionId,
        streamKey
    )
    if (streamingActive) {
        return null
    }
    if (isPromptVisible) {
        return (
            <MessageTemplate type="ai">
                <div className="flex flex-col gap-2">
                    <span className="text-xs text-muted">How is PostHog AI doing? (optional)</span>
                    <FeedbackPromptRating sessionId={sessionId} streamKey={streamKey} />
                </div>
            </MessageTemplate>
        )
    }
    if (isDetailedFeedbackVisible) {
        return <FeedbackPromptDetails sessionId={sessionId} sessionKind={sessionKind} streamKey={streamKey} />
    }
    if (isThankYouVisible) {
        return (
            <MessageTemplate type="ai">
                <p className="m-0 text-sm text-secondary">Thanks for your feedback and using PostHog AI!</p>
            </MessageTemplate>
        )
    }
    return null
})
