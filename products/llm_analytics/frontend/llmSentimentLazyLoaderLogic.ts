import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { llmSentimentLazyLoaderLogicType } from './llmSentimentLazyLoaderLogicType'

interface MessageSentiment {
    index: number
    label: string
    score: number
    scores: Record<string, number>
}

export interface GenerationSentiment {
    label: string
    score: number
    scores: Record<string, number>
    messages: MessageSentiment[]
}

export interface SentimentResult {
    trace_id: string
    label: string
    score: number
    scores: Record<string, number>
    generations: Record<string, GenerationSentiment>
    generation_count: number
    message_count: number
}

interface BatchSentimentResponse {
    results: Record<string, SentimentResult | { error: string }>
}

function isValidSentimentResult(value: unknown): value is SentimentResult {
    return !!value && typeof value === 'object' && 'label' in value && !('error' in value)
}

const BATCH_MAX_SIZE = 25

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

export const llmSentimentLazyLoaderLogic = kea<llmSentimentLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmSentimentLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        ensureSentimentLoaded: (traceId: string) => ({ traceId }),
        loadSentimentBatchSuccess: (results: Record<string, SentimentResult | null>, requestedTraceIds: string[]) => ({
            results,
            requestedTraceIds,
        }),
        loadSentimentBatchFailure: (requestedTraceIds: string[]) => ({ requestedTraceIds }),
    }),

    reducers({
        sentimentByTraceId: [
            {} as Record<string, SentimentResult | null>,
            {
                loadSentimentBatchSuccess: (state, { results, requestedTraceIds }) => {
                    const newState = { ...state }

                    for (const traceId of requestedTraceIds) {
                        newState[traceId] = results[traceId] ?? null
                    }

                    return newState
                },
                loadSentimentBatchFailure: (state, { requestedTraceIds }) => {
                    const newState = { ...state }

                    for (const traceId of requestedTraceIds) {
                        newState[traceId] = null
                    }

                    return newState
                },
            },
        ],

        loadingTraceIds: [
            new Set<string>(),
            {
                ensureSentimentLoaded: (state, { traceId }) => {
                    if (state.has(traceId)) {
                        return state
                    }

                    const newSet = new Set(state)
                    newSet.add(traceId)
                    return newSet
                },
                loadSentimentBatchSuccess: (state, { requestedTraceIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedTraceIds) {
                        newSet.delete(id)
                    }

                    return newSet
                },
                loadSentimentBatchFailure: (state, { requestedTraceIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedTraceIds) {
                        newSet.delete(id)
                    }

                    return newSet
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
        getTraceSentiment: [
            (s) => [s.sentimentByTraceId],
            (sentimentByTraceId): ((traceId: string) => SentimentResult | null | undefined) => {
                return (traceId: string) => sentimentByTraceId[traceId]
            },
        ],
        getGenerationSentiment: [
            (s) => [s.sentimentByTraceId],
            (sentimentByTraceId): ((traceId: string, generationEventId: string) => GenerationSentiment | undefined) => {
                return (traceId: string, generationEventId: string) =>
                    sentimentByTraceId[traceId]?.generations?.[generationEventId]
            },
        ],
    }),

    listeners(({ values, actions }) => {
        let pendingTraceIds = new Set<string>()
        let batchTimer: ReturnType<typeof setTimeout> | null = null

        return {
            ensureSentimentLoaded: ({ traceId }) => {
                if (values.sentimentByTraceId[traceId] !== undefined) {
                    return
                }

                pendingTraceIds.add(traceId)

                if (batchTimer) {
                    return
                }

                batchTimer = setTimeout(async () => {
                    const allIds = Array.from(pendingTraceIds)
                    pendingTraceIds = new Set()
                    batchTimer = null

                    if (allIds.length === 0) {
                        return
                    }

                    const teamId = values.currentTeamId

                    if (!teamId) {
                        return
                    }

                    const chunks = chunk(allIds, BATCH_MAX_SIZE)

                    for (const batch of chunks) {
                        try {
                            const response = await api.create<BatchSentimentResponse>(
                                `api/environments/${teamId}/llm_analytics/sentiment/batch/`,
                                { trace_ids: batch }
                            )

                            const results: Record<string, SentimentResult | null> = {}

                            for (const traceId of batch) {
                                const raw = response.results[traceId]
                                results[traceId] = isValidSentimentResult(raw) ? raw : null
                            }

                            actions.loadSentimentBatchSuccess(results, batch)
                        } catch {
                            actions.loadSentimentBatchFailure(batch)
                        }
                    }
                }, 0)
            },
        }
    }),
])
