import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { type MessageRatingOrNull, messageRatingsLogic } from '../logics/messageRatingsLogic'
import { captureTurnFeedbackText, captureTurnRating } from '../utils/feedbackEvents'
import type { TurnRatingTarget } from './turnFeedbackTypes'

export type TurnFeedbackInputStatus = 'hidden' | 'pending' | 'submitted'

export function useTurnRating({ sessionId, turnIndex, run, traceId }: TurnRatingTarget): {
    rating: MessageRatingOrNull
    submitRating: (rating: 'good' | 'bad') => void
    feedback: string
    setFeedback: (feedback: string) => void
    feedbackInputStatus: TurnFeedbackInputStatus
    closeFeedback: () => void
    submitFeedback: () => void
} {
    const { ratingForKey } = useValues(messageRatingsLogic)
    const { setRating } = useActions(messageRatingsLogic)
    const ratingKey = `${sessionId}:turn-${turnIndex}`
    const rating = ratingForKey(ratingKey)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<TurnFeedbackInputStatus>('hidden')

    return {
        rating,
        submitRating: (newRating) => {
            if (rating) {
                return // Already rated
            }
            setRating({ key: ratingKey, rating: newRating })
            captureTurnRating(sessionId, traceId ?? null, newRating, turnIndex, run)
            if (newRating === 'bad') {
                setFeedbackInputStatus('pending')
            }
        },
        feedback,
        setFeedback,
        feedbackInputStatus,
        closeFeedback: () => setFeedbackInputStatus('hidden'),
        submitFeedback: () => {
            if (!feedback) {
                return // Input is empty
            }
            captureTurnFeedbackText(sessionId, traceId ?? null, feedback, turnIndex, run)
            setFeedbackInputStatus('submitted')
        },
    }
}
