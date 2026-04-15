import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { llmGenerationSentimentLazyLoaderLogicType } from './llmGenerationSentimentLazyLoaderLogicType'
import type { GenerationSentiment } from './llmSentimentLazyLoaderLogic'

export interface GenerationSentimentDateRange {
    dateFrom?: string | null
    dateTo?: string | null
}

interface BatchGenerationSentimentResponse {
    results: Record<string, GenerationSentiment | { error: string }>
}

function isValidGenerationSentiment(value: unknown): value is GenerationSentiment {
    return !!value && typeof value === 'object' && 'label' in value && !('error' in value)
}

const BATCH_MAX_SIZE = 5

function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

export const llmGenerationSentimentLazyLoaderLogic = kea<llmGenerationSentimentLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmGenerationSentimentLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        ensureGenerationSentimentLoaded: (generationId: string, dateRange?: GenerationSentimentDateRange) => ({
            generationId,
            dateRange,
        }),
        loadGenerationSentimentBatchSuccess: (
            results: Record<string, GenerationSentiment | null>,
            requestedGenerationIds: string[]
        ) => ({
            results,
            requestedGenerationIds,
        }),
        loadGenerationSentimentBatchFailure: (requestedGenerationIds: string[]) => ({ requestedGenerationIds }),
        clearLoadingGeneration: (generationId: string) => ({ generationId }),
    }),

    reducers({
        sentimentByGenerationId: [
            {} as Record<string, GenerationSentiment | null>,
            {
                loadGenerationSentimentBatchSuccess: (state, { results, requestedGenerationIds }) => {
                    const newState = { ...state }

                    for (const generationId of requestedGenerationIds) {
                        newState[generationId] = results[generationId] ?? null
                    }

                    return newState
                },
                loadGenerationSentimentBatchFailure: (state, { requestedGenerationIds }) => {
                    const newState = { ...state }

                    for (const generationId of requestedGenerationIds) {
                        newState[generationId] = null
                    }

                    return newState
                },
            },
        ],

        loadingGenerationIds: [
            new Set<string>(),
            {
                ensureGenerationSentimentLoaded: (state, { generationId }) => {
                    if (state.has(generationId)) {
                        return state
                    }

                    const newSet = new Set(state)
                    newSet.add(generationId)
                    return newSet
                },
                loadGenerationSentimentBatchSuccess: (state, { requestedGenerationIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedGenerationIds) {
                        newSet.delete(id)
                    }

                    return newSet
                },
                loadGenerationSentimentBatchFailure: (state, { requestedGenerationIds }) => {
                    const newSet = new Set(state)

                    for (const id of requestedGenerationIds) {
                        newSet.delete(id)
                    }

                    return newSet
                },
                clearLoadingGeneration: (state, { generationId }) => {
                    if (!state.has(generationId)) {
                        return state
                    }
                    const newSet = new Set(state)
                    newSet.delete(generationId)
                    return newSet
                },
            },
        ],
    }),

    selectors({
        isGenerationLoading: [
            (s) => [s.loadingGenerationIds],
            (loadingGenerationIds): ((generationId: string) => boolean) => {
                return (generationId: string) => loadingGenerationIds.has(generationId)
            },
        ],
        getGenerationSentiment: [
            (s) => [s.sentimentByGenerationId],
            (sentimentByGenerationId): ((generationId: string) => GenerationSentiment | null | undefined) => {
                return (generationId: string) => sentimentByGenerationId[generationId]
            },
        ],
    }),

    listeners(({ values, actions }) => {
        let pendingGenerationIds = new Set<string>()
        let batchTimer: ReturnType<typeof setTimeout> | null = null
        let pendingDateRange: GenerationSentimentDateRange | undefined

        return {
            ensureGenerationSentimentLoaded: ({ generationId, dateRange }) => {
                if (values.sentimentByGenerationId[generationId] !== undefined) {
                    actions.clearLoadingGeneration(generationId)
                    return
                }

                pendingGenerationIds.add(generationId)
                if (dateRange) {
                    pendingDateRange = dateRange
                }

                if (batchTimer) {
                    return
                }

                batchTimer = setTimeout(async () => {
                    const allIds = Array.from(pendingGenerationIds)
                    const dateRangeForBatch = pendingDateRange
                    pendingGenerationIds = new Set()
                    pendingDateRange = undefined
                    batchTimer = null

                    if (allIds.length === 0) {
                        return
                    }

                    const teamId = values.currentTeamId

                    if (!teamId) {
                        return
                    }

                    const chunks = chunk(allIds, BATCH_MAX_SIZE)

                    await Promise.allSettled(
                        chunks.map(async (batch) => {
                            try {
                                const response = await api.create<BatchGenerationSentimentResponse>(
                                    `api/environments/${teamId}/llm_analytics/sentiment/`,
                                    {
                                        ids: batch,
                                        analysis_level: 'generation',
                                        date_from: dateRangeForBatch?.dateFrom || undefined,
                                        date_to: dateRangeForBatch?.dateTo || undefined,
                                    }
                                )

                                const results: Record<string, GenerationSentiment | null> = {}

                                for (const generationId of batch) {
                                    const raw = response.results[generationId]
                                    results[generationId] = isValidGenerationSentiment(raw) ? raw : null
                                }

                                actions.loadGenerationSentimentBatchSuccess(results, batch)
                            } catch {
                                actions.loadGenerationSentimentBatchFailure(batch)
                            }
                        })
                    )
                }, 0)
            },
        }
    }),
])
