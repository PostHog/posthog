import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { messageRatingsLogicType } from './messageRatingsLogicType'

export type MessageRating = 'good' | 'bad'
export type MessageRatingOrNull = MessageRating | null

const MAX_STORED_RATINGS = 1000

/**
 * Persists run-thread message ratings ("good"/"bad") keyed by trace ID.
 *
 * Uses Kea's localStorage plugin for automatic persistence.
 */
export const messageRatingsLogic = kea<messageRatingsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'messageRatingsLogic']),

    actions({
        setRatingForTraceId: (payload: { traceId: string; rating: MessageRating }) => ({
            traceId: payload.traceId.trim(),
            rating: payload.rating,
        }),
        clearRatingForTraceId: (payload: { traceId: string }) => ({ traceId: payload.traceId.trim() }),
        clearAllRatings: true,
        pruneOldRatings: true,
    }),

    reducers({
        ratingsByTraceId: [
            {} as Record<string, MessageRating>,
            { persist: true, storageKey: 'posthog_ai_run_ratings' },
            {
                setRatingForTraceId: (state, { traceId, rating }) => ({
                    ...state,
                    [traceId]: rating,
                }),
                clearRatingForTraceId: (state, { traceId }) => {
                    if (!(traceId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[traceId]
                    return next
                },
                clearAllRatings: () => ({}),
                pruneOldRatings: (state) => {
                    const entries = Object.entries(state)
                    if (entries.length <= MAX_STORED_RATINGS) {
                        return state
                    }
                    return Object.fromEntries(entries.slice(-MAX_STORED_RATINGS))
                },
            },
        ],
    }),

    selectors({
        ratingForTraceId: [
            (s) => [s.ratingsByTraceId],
            (ratingsByTraceId: Record<string, MessageRating>) => {
                return (traceId: string | null | undefined): MessageRatingOrNull => {
                    if (!traceId) {
                        return null
                    }
                    return ratingsByTraceId[traceId] ?? null
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setRatingForTraceId: () => {
            // Prune old ratings if we've exceeded the limit
            if (Object.keys(values.ratingsByTraceId).length > MAX_STORED_RATINGS) {
                actions.pruneOldRatings()
            }
        },
    })),
])
