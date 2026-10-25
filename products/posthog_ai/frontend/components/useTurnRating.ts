import { captureTurnFeedbackDialogClosed, captureTurnFeedbackText, captureTurnRating } from '../utils/feedbackEvents'
import type { TurnRatingTarget } from './turnFeedbackTypes'
import { type AnswerRating, useAnswerRating } from './useAnswerRating'

export function useTurnRating({ sessionId, turnIndex, run, traceId }: TurnRatingTarget): AnswerRating {
    // A trace id names one turn however the thread numbers its turns, so a stored rating stays on its answer.
    const ratingKey = traceId ?? `${sessionId}:turn-${turnIndex}`
    const eventTraceId = traceId ?? null

    return useAnswerRating(ratingKey, {
        onRate: (rating) => captureTurnRating(sessionId, eventTraceId, rating, turnIndex, run),
        onFeedbackText: (text) => captureTurnFeedbackText(sessionId, eventTraceId, text, turnIndex, run),
        onFeedbackDialogClosed: (outcome, hasText) =>
            captureTurnFeedbackDialogClosed(sessionId, eventTraceId, outcome, hasText, turnIndex, run),
    })
}
