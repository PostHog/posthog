import { BindLogic, useValues } from 'kea'

import { feedbackPromptLogic } from '../../logics/feedbackPromptLogic'
import { isTerminalRunStatus, runStreamLogic } from '../../logics/runStreamLogic'
import { MessageTemplate } from '../../messages/MessageTemplate'
import { FeedbackDisplay } from './FeedbackDisplay'
import { FeedbackPrompt } from './FeedbackPrompt'
import { MessageFeedbackActions } from './MessageFeedbackActions'

export interface RunFeedbackFooterProps {
    /** Stream/logic key of the run (matches the bound `runStreamLogic`). */
    streamKey: string
    /** Telemetry session id — the conversation id when there is one, else the run id. */
    sessionId: string
}

/**
 * Feedback footer for a live run. Shows the per-run thumbs once the turn settles, plus the progressive
 * good/okay/bad prompt (and its detailed-feedback / thank-you states) that `feedbackPromptLogic` surfaces.
 * Binds `feedbackPromptLogic` so its children read it from context and its `runStreamLogic` listeners run.
 */
export function RunFeedbackFooter({ streamKey, sessionId }: RunFeedbackFooterProps): JSX.Element | null {
    return (
        <BindLogic logic={feedbackPromptLogic} props={{ streamKey, sessionId }}>
            <RunFeedbackFooterContent sessionId={sessionId} />
        </BindLogic>
    )
}

function RunFeedbackFooterContent({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { traceId, turnComplete, currentRunStatus } = useValues(runStreamLogic)
    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible } = useValues(feedbackPromptLogic)

    // Feedback only makes sense once the run has settled — don't rate a turn still streaming.
    const runSettled = turnComplete || isTerminalRunStatus(currentRunStatus)
    if (!runSettled) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 px-4 pb-2">
            <MessageFeedbackActions traceId={traceId} />
            {isPromptVisible && (
                <MessageTemplate type="ai">
                    <div className="flex flex-col gap-2">
                        <p className="m-0 font-medium">How is PostHog AI doing? (optional)</p>
                        <FeedbackDisplay />
                    </div>
                </MessageTemplate>
            )}
            {isDetailedFeedbackVisible && <FeedbackPrompt sessionId={sessionId} />}
            {isThankYouVisible && (
                <MessageTemplate type="ai">
                    <p className="m-0 text-sm text-secondary">Thanks for your feedback and using PostHog AI!</p>
                </MessageTemplate>
            )}
        </div>
    )
}
