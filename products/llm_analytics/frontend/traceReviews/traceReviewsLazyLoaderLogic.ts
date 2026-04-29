import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { traceReviewsApi } from './traceReviewsApi'
import type { traceReviewsLazyLoaderLogicType } from './traceReviewsLazyLoaderLogicType'
import type { TraceReview } from './types'

const BATCH_MAX_SIZE = 100

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []

    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }

    return chunks
}

export const traceReviewsLazyLoaderLogic = kea<traceReviewsLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceReviews', 'traceReviewsLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        ensureReviewsLoaded: (traceIds: string[]) => ({ traceIds }),
        markTraceIdsLoading: (traceIds: string[]) => ({ traceIds }),
        setTraceReview: (review: TraceReview) => ({ review }),
        setTraceAsUnreviewed: (traceId: string) => ({ traceId }),
        loadReviewsBatchSuccess: (results: Record<string, TraceReview | null>, requestedTraceIds: string[]) => ({
            results,
            requestedTraceIds,
        }),
        loadReviewsBatchFailure: (requestedTraceIds: string[]) => ({ requestedTraceIds }),
    }),

    reducers({
        reviewsByTraceId: [
            {} as Record<string, TraceReview | null>,
            {
                setTraceReview: (state, { review }) => ({
                    ...state,
                    [review.trace_id]: review,
                }),
                setTraceAsUnreviewed: (state, { traceId }) => ({
                    ...state,
                    [traceId]: null,
                }),
                loadReviewsBatchSuccess: (state, { results, requestedTraceIds }) => {
                    const nextState = { ...state }

                    for (const traceId of requestedTraceIds) {
                        nextState[traceId] = results[traceId] ?? null
                    }

                    return nextState
                },
            },
        ],

        loadingTraceIds: [
            new Set<string>(),
            {
                setTraceReview: (state, { review }) => {
                    const nextState = new Set(state)
                    nextState.delete(review.trace_id)
                    return nextState
                },
                setTraceAsUnreviewed: (state, { traceId }) => {
                    const nextState = new Set(state)
                    nextState.delete(traceId)
                    return nextState
                },
                markTraceIdsLoading: (state, { traceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of traceIds) {
                        if (traceId) {
                            nextState.add(traceId)
                        }
                    }

                    return nextState
                },
                loadReviewsBatchSuccess: (state, { requestedTraceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of requestedTraceIds) {
                        nextState.delete(traceId)
                    }

                    return nextState
                },
                loadReviewsBatchFailure: (state, { requestedTraceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of requestedTraceIds) {
                        nextState.delete(traceId)
                    }

                    return nextState
                },
            },
        ],

        failedTraceIds: [
            new Set<string>(),
            {
                setTraceReview: (state, { review }) => {
                    const nextState = new Set(state)
                    nextState.delete(review.trace_id)
                    return nextState
                },
                setTraceAsUnreviewed: (state, { traceId }) => {
                    const nextState = new Set(state)
                    nextState.delete(traceId)
                    return nextState
                },
                markTraceIdsLoading: (state, { traceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of traceIds) {
                        nextState.delete(traceId)
                    }

                    return nextState
                },
                loadReviewsBatchSuccess: (state, { requestedTraceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of requestedTraceIds) {
                        nextState.delete(traceId)
                    }

                    return nextState
                },
                loadReviewsBatchFailure: (state, { requestedTraceIds }) => {
                    const nextState = new Set(state)

                    for (const traceId of requestedTraceIds) {
                        nextState.add(traceId)
                    }

                    return nextState
                },
            },
        ],
    }),

    selectors({
        isTraceLoading: [
            (s) => [s.loadingTraceIds],
            (loadingTraceIds): ((traceId: string) => boolean) => {
                return (traceId: string) => loadingTraceIds.has(traceId)
            },
        ],
        getTraceReview: [
            (s) => [s.reviewsByTraceId],
            (reviewsByTraceId): ((traceId: string) => TraceReview | null | undefined) => {
                return (traceId: string) => reviewsByTraceId[traceId]
            },
        ],
        didTraceReviewLoadFail: [
            (s) => [s.failedTraceIds],
            (failedTraceIds): ((traceId: string) => boolean) => {
                return (traceId: string) => failedTraceIds.has(traceId)
            },
        ],
    }),

    listeners(({ actions, values }) => {
        let pendingTraceIds = new Set<string>()
        let batchTimer: ReturnType<typeof setTimeout> | null = null

        return {
            ensureReviewsLoaded: ({ traceIds }) => {
                const uncachedTraceIds = traceIds.filter(
                    (traceId) =>
                        traceId &&
                        values.reviewsByTraceId[traceId] === undefined &&
                        !values.loadingTraceIds.has(traceId)
                )

                if (uncachedTraceIds.length === 0) {
                    return
                }

                actions.markTraceIdsLoading(uncachedTraceIds)

                for (const traceId of uncachedTraceIds) {
                    pendingTraceIds.add(traceId)
                }

                if (batchTimer) {
                    return
                }

                batchTimer = setTimeout(async () => {
                    const requestedTraceIds = Array.from(pendingTraceIds)
                    pendingTraceIds = new Set()
                    batchTimer = null

                    const teamId = values.currentTeamId
                    if (!teamId || requestedTraceIds.length === 0) {
                        actions.loadReviewsBatchFailure(requestedTraceIds)
                        return
                    }

                    const traceIdChunks = chunk(requestedTraceIds, BATCH_MAX_SIZE)

                    await Promise.allSettled(
                        traceIdChunks.map(async (traceIdsChunk) => {
                            try {
                                const response = await traceReviewsApi.list(
                                    {
                                        trace_id__in: traceIdsChunk,
                                        limit: traceIdsChunk.length,
                                    },
                                    teamId
                                )

                                const resultsByTraceId = Object.fromEntries(
                                    response.results.map((review) => [review.trace_id, review] as const)
                                )

                                actions.loadReviewsBatchSuccess(resultsByTraceId, traceIdsChunk)
                            } catch {
                                actions.loadReviewsBatchFailure(traceIdsChunk)
                            }
                        })
                    )
                }, 0)
            },
        }
    }),
])
