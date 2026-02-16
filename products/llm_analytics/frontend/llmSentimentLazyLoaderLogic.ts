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

export const llmSentimentLazyLoaderLogic = kea<llmSentimentLazyLoaderLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmSentimentLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadSentiment: (traceId: string) => ({ traceId }),
        sentimentLoaded: (traceId: string, result: SentimentResult) => ({ traceId, result }),
        sentimentLoadFailed: (traceId: string) => ({ traceId }),
    }),

    reducers({
        sentimentByTraceId: [
            {} as Record<string, SentimentResult>,
            {
                sentimentLoaded: (state, { traceId, result }) => ({ ...state, [traceId]: result }),
            },
        ],
        loadingTraceIds: [
            new Set<string>(),
            {
                loadSentiment: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.add(traceId)
                    return newSet
                },
                sentimentLoaded: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
                sentimentLoadFailed: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
            },
        ],
        failedTraceIds: [
            new Set<string>(),
            {
                sentimentLoadFailed: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.add(traceId)
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
            (sentimentByTraceId): ((traceId: string) => SentimentResult | undefined) => {
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

    listeners(({ values, actions }) => ({
        loadSentiment: async ({ traceId }) => {
            // Skip if already loaded or in-flight
            if (values.sentimentByTraceId[traceId] || values.failedTraceIds.has(traceId)) {
                return
            }

            const teamId = values.currentTeamId
            if (!teamId) {
                return
            }

            try {
                const result = await api.create<SentimentResult>(
                    `api/environments/${teamId}/llm_analytics/sentiment/`,
                    { trace_id: traceId }
                )
                actions.sentimentLoaded(traceId, result)
            } catch {
                actions.sentimentLoadFailed(traceId)
            }
        },
    })),
])
