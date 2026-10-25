import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { type MessageRating, type MessageRatingOrNull, messageRatingsLogic } from '../logics/messageRatingsLogic'
import type { FeedbackDialogOutcome } from '../utils/feedbackEvents'

export interface AnswerRatingHandlers {
    onRate: (rating: MessageRating) => void
    /** Called only when the user wrote something. Receives the trimmed text. */
    onFeedbackText: (text: string) => void
    onFeedbackDialogClosed: (outcome: FeedbackDialogOutcome, hasText: boolean) => void
}

export interface AnswerRating {
    rating: MessageRatingOrNull
    submitRating: (rating: MessageRating) => void
    isFeedbackDialogOpen: boolean
    closeFeedbackDialog: (outcome: FeedbackDialogOutcome, text: string) => void
}

/**
 * Thumbs up/down on one answer, plus the feedback dialog a thumbs-down opens. The dialog opens at most once
 * per answer: any close is final, so a second thumbs-down click does nothing. Each caller sends its own events.
 */
export function useAnswerRating(ratingKey: string | null | undefined, handlers: AnswerRatingHandlers): AnswerRating {
    const { ratingForKey, isFeedbackDialogClosedForKey } = useValues(messageRatingsLogic)
    const { setRating, markFeedbackDialogClosed } = useActions(messageRatingsLogic)
    const rating = ratingForKey(ratingKey)
    const [isFeedbackDialogOpen, setIsFeedbackDialogOpen] = useState(false)

    return {
        rating,
        submitRating: (newRating) => {
            if (!ratingKey) {
                return
            }
            if (rating) {
                // The dialog was never closed, for example because the page reloaded while it was open.
                if (rating === 'bad' && newRating === 'bad' && !isFeedbackDialogClosedForKey(ratingKey)) {
                    setIsFeedbackDialogOpen(true)
                }
                return
            }
            setRating({ key: ratingKey, rating: newRating })
            handlers.onRate(newRating)
            if (newRating === 'bad') {
                setIsFeedbackDialogOpen(true)
            }
        },
        isFeedbackDialogOpen,
        closeFeedbackDialog: (outcome, text) => {
            // The dialog stays clickable while its close animation runs, so a second close can arrive.
            if (!ratingKey || !isFeedbackDialogOpen) {
                return
            }
            const trimmedText = text.trim()
            if (outcome === 'submitted' && trimmedText) {
                handlers.onFeedbackText(trimmedText)
            }
            handlers.onFeedbackDialogClosed(outcome, !!trimmedText)
            markFeedbackDialogClosed({ key: ratingKey })
            setIsFeedbackDialogOpen(false)
            if (outcome === 'submitted') {
                // A Lemon toast because its container is mounted on every app shell, quill skin included.
                lemonToast.success('Thank you for your feedback!')
            }
        },
    }
}
