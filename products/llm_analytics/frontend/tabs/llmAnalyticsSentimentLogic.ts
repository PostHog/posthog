import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import sentimentGenerationsQueryTemplate from '../../backend/queries/sentiment_generations.sql?raw'
import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { llmGenerationSentimentLazyLoaderLogic } from '../llmGenerationSentimentLazyLoaderLogic'
import type { GenerationSentiment, MessageSentiment } from '../llmSentimentLazyLoaderLogic'
import { extractContentText } from '../sentimentUtils'
import type { llmAnalyticsSentimentLogicType } from './llmAnalyticsSentimentLogicType'

export type SentimentFilterLabel = 'positive' | 'negative' | 'both'
export type SentimentFeedbackLabel = 'positive' | 'negative' | 'neutral'

export interface SentimentGeneration {
    uuid: string
    traceId: string
    aiInput: unknown
    model: string | null
    distinctId: string
    timestamp: string
}

/** A generation paired with the index of the best matching message for display */
export interface SentimentCard {
    generation: SentimentGeneration
    /** Index into the generation's user messages array for the highest-intensity matching message */
    messageIndex: number
    sentiment: MessageSentiment
}

export interface LLMAnalyticsSentimentLogicProps {
    tabId?: string
}

const GENERATIONS_PAGE_SIZE = 200
// Match backend MAX_MESSAGE_CHARS (2000) so training data captures the same text window the model classified
const SNIPPET_MAX_LENGTH = 2000

function getSnippetFromCard(card: SentimentCard): string {
    try {
        const parsed =
            typeof card.generation.aiInput === 'string' ? JSON.parse(card.generation.aiInput) : card.generation.aiInput
        if (!Array.isArray(parsed)) {
            return ''
        }
        const msg = parsed[card.messageIndex]
        const text = extractContentText(msg?.content)
        return text.slice(-SNIPPET_MAX_LENGTH)
    } catch {
        return ''
    }
}

interface GenerationsQueryValues {
    dateFilter: { dateFrom: string | null; dateTo: string | null }
    shouldFilterTestAccounts: boolean
    propertyFilters: unknown[]
}

async function fetchGenerations(values: GenerationsQueryValues, cursor: string | null): Promise<SentimentGeneration[]> {
    const response = (await api.query({
        kind: NodeKind.HogQLQuery,
        query: sentimentGenerationsQueryTemplate,
        filters: {
            dateRange: {
                date_from: values.dateFilter.dateFrom || null,
                date_to: cursor || values.dateFilter.dateTo || null,
            },
            filterTestAccounts: values.shouldFilterTestAccounts,
            properties: values.propertyFilters,
        },
    })) as HogQLQueryResponse

    return (response.results || []).map((row) => ({
        uuid: row[0] as string,
        traceId: row[1] as string,
        aiInput: row[2],
        model: row[3] as string | null,
        distinctId: row[4] as string,
        timestamp: row[5] as string,
    }))
}

export const llmAnalyticsSentimentLogic = kea<llmAnalyticsSentimentLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsSentimentLogic']),
    key((props: LLMAnalyticsSentimentLogicProps) => props.tabId || 'default'),
    props({} as LLMAnalyticsSentimentLogicProps),
    connect((props: LLMAnalyticsSentimentLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            llmGenerationSentimentLazyLoaderLogic,
            ['sentimentByGenerationId'],
        ],
        actions: [llmGenerationSentimentLazyLoaderLogic, ['ensureGenerationSentimentLoaded']],
    })),

    actions({
        setSentimentFilter: (sentimentFilter: SentimentFilterLabel) => ({ sentimentFilter }),
        setIntensityThreshold: (intensityThreshold: number) => ({ intensityThreshold }),
        toggleCardExpanded: (generationId: string) => ({ generationId }),
        loadMoreGenerations: true,
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        submitSentimentFeedback: (cardKey: string, feedbackLabel: SentimentFeedbackLabel, card: SentimentCard) => ({
            cardKey,
            feedbackLabel,
            card,
        }),
    }),

    reducers({
        sentimentFilter: [
            'both' as SentimentFilterLabel,
            {
                setSentimentFilter: (_, { sentimentFilter }) => sentimentFilter,
            },
        ],
        intensityThreshold: [
            0.5,
            {
                setIntensityThreshold: (_, { intensityThreshold }) => intensityThreshold,
            },
        ],
        expandedCardIds: [
            new Set<string>(),
            {
                toggleCardExpanded: (state, { generationId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(generationId)) {
                        newSet.delete(generationId)
                    } else {
                        newSet.add(generationId)
                    }
                    return newSet
                },
                loadGenerations: () => new Set<string>(),
            },
        ],
        hasMore: [
            true as boolean,
            {
                setHasMore: (_, { hasMore }) => hasMore,
                loadGenerations: () => true,
            },
        ],
        feedbackByCardKey: [
            {} as Record<string, SentimentFeedbackLabel>,
            {
                submitSentimentFeedback: (state, { cardKey, feedbackLabel }) => ({
                    ...state,
                    [cardKey]: feedbackLabel,
                }),
                loadGenerations: () => ({}),
            },
        ],
    }),

    loaders(({ values }) => ({
        generations: [
            [] as SentimentGeneration[],
            {
                loadGenerations: async () => {
                    return await fetchGenerations(values, null)
                },
                loadMoreGenerations: async () => {
                    const existing = values.generations
                    const cursor = existing.length > 0 ? existing[existing.length - 1].timestamp : null
                    const newGenerations = await fetchGenerations(values, cursor)
                    // Dedupe by traceId in case of timestamp boundary overlap
                    const existingTraceIds = new Set(existing.map((g) => g.traceId))
                    const unique = newGenerations.filter((g) => !existingTraceIds.has(g.traceId))
                    return [...existing, ...unique]
                },
            },
        ],
    })),

    selectors({
        taxonomicGroupTypes: [
            (s) => [s.groupsTaxonomicTypes],
            (groupsTaxonomicTypes: TaxonomicFilterGroupType[]): TaxonomicFilterGroupType[] => [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ],
        ],
        sentimentCards: [
            (s) => [s.generations, s.sentimentByGenerationId, s.sentimentFilter, s.intensityThreshold],
            (
                generations: SentimentGeneration[],
                sentimentByGenerationId: Record<string, GenerationSentiment | null>,
                sentimentFilter: SentimentFilterLabel,
                intensityThreshold: number
            ): SentimentCard[] => {
                const cards: SentimentCard[] = []
                for (const gen of generations) {
                    const sentimentData = sentimentByGenerationId[gen.uuid]
                    if (!sentimentData?.messages) {
                        continue
                    }
                    // Find the highest-intensity message that matches the filter
                    let bestIndex = -1
                    let bestScore = 0
                    let bestSentiment: MessageSentiment | null = null
                    for (const [idx, msg] of Object.entries(sentimentData.messages)) {
                        const matches =
                            sentimentFilter !== 'both'
                                ? msg.label === sentimentFilter && msg.score >= intensityThreshold
                                : msg.label !== 'neutral' && msg.score >= intensityThreshold
                        if (matches && msg.score > bestScore) {
                            bestIndex = Number(idx)
                            bestScore = msg.score
                            bestSentiment = msg
                        }
                    }
                    if (bestSentiment && bestIndex >= 0) {
                        cards.push({ generation: gen, messageIndex: bestIndex, sentiment: bestSentiment })
                    }
                }
                return cards
            },
        ],
        stillAnalyzing: [
            (s) => [s.generations, s.sentimentByGenerationId],
            (
                generations: SentimentGeneration[],
                sentimentByGenerationId: Record<string, GenerationSentiment | null>
            ): boolean => generations.some((gen) => sentimentByGenerationId[gen.uuid] === undefined),
        ],
    }),

    listeners(({ values, actions }) => {
        let preLoadMoreCount = 0

        return {
            loadGenerationsSuccess: ({ generations }) => {
                actions.setHasMore(generations.length >= GENERATIONS_PAGE_SIZE)
                for (const gen of generations) {
                    if (values.sentimentByGenerationId[gen.uuid] === undefined) {
                        actions.ensureGenerationSentimentLoaded(gen.uuid, values.dateFilter)
                    }
                }
            },
            loadMoreGenerations: () => {
                preLoadMoreCount = values.generations.length
            },
            loadMoreGenerationsSuccess: () => {
                const newCount = values.generations.length - preLoadMoreCount
                actions.setHasMore(newCount >= GENERATIONS_PAGE_SIZE)
                for (const gen of values.generations) {
                    if (values.sentimentByGenerationId[gen.uuid] === undefined) {
                        actions.ensureGenerationSentimentLoaded(gen.uuid, values.dateFilter)
                    }
                }
            },
            submitSentimentFeedback: ({ card, feedbackLabel }) => {
                posthog.capture('llma sentiment feedback', {
                    generation_uuid: card.generation.uuid,
                    trace_id: card.generation.traceId,
                    message_index: card.messageIndex,
                    message_text_snippet: getSnippetFromCard(card),
                    model_prediction_label: card.sentiment.label,
                    model_prediction_score: card.sentiment.score,
                    user_label: feedbackLabel,
                    ai_model: card.generation.model,
                })
            },
        }
    }),

    subscriptions(({ actions }) => ({
        dateFilter: () => actions.loadGenerations(),
        shouldFilterTestAccounts: () => actions.loadGenerations(),
        propertyFilters: () => actions.loadGenerations(),
    })),

    afterMount(({ actions }) => {
        actions.loadGenerations()
    }),
])
