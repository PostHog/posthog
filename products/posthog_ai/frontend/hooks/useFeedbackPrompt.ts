import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { feedbackPromptLogic } from '../logics/feedbackPromptLogic'
import { runStreamLogic } from '../logics/runStreamLogic'

export interface UseFeedbackPromptResult {
    isPromptVisible: boolean
    isDetailedFeedbackVisible: boolean
    isThankYouVisible: boolean
    streamingActive: boolean
}

/**
 * Drives the periodic feedback prompt off the bound `runStreamLogic`: checks the trigger rules each time a
 * turn finishes, and treats a new message sent while the prompt is open as an implicit dismissal.
 */
export function useFeedbackPrompt(sessionId: string, streamKey: string): UseFeedbackPromptResult {
    const { threadItems, streamPhase } = useValues(runStreamLogic)
    const logic = feedbackPromptLogic({ sessionId, streamKey })
    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible } = useValues(logic)
    const { checkShouldShowPrompt, implicitDismissPrompt, implicitDismissDetailedFeedback } = useActions(logic)

    const streamingActive = streamPhase !== 'idle'
    const humanMessageCount = useMemo(
        () => threadItems.filter((item) => item.type === 'human_message').length,
        [threadItems]
    )
    const prevMessageCountRef = useRef(humanMessageCount)
    const prevStreamingActiveRef = useRef(streamingActive)

    useEffect(() => {
        const wasStreaming = prevStreamingActiveRef.current
        const prevCount = prevMessageCountRef.current

        if (wasStreaming && !streamingActive && humanMessageCount > 0) {
            checkShouldShowPrompt(humanMessageCount)
        }
        if (isPromptVisible && humanMessageCount > prevCount && streamingActive) {
            implicitDismissPrompt()
        }
        if (isDetailedFeedbackVisible && humanMessageCount > prevCount && streamingActive) {
            implicitDismissDetailedFeedback()
        }

        prevMessageCountRef.current = humanMessageCount
        prevStreamingActiveRef.current = streamingActive
    }, [
        humanMessageCount,
        streamingActive,
        isPromptVisible,
        isDetailedFeedbackVisible,
        checkShouldShowPrompt,
        implicitDismissPrompt,
        implicitDismissDetailedFeedback,
    ])

    return { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible, streamingActive }
}
