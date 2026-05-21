import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCurrentTeamId } from '~/lib/utils/getAppContext'
import { groupsModel } from '~/models/groupsModel'

import { llmAnalyticsSentimentGenerationsCreate } from '../generated/api'
import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { llmGenerationSentimentLazyLoaderLogic } from '../llmGenerationSentimentLazyLoaderLogic'
import type { GenerationSentiment, MessageSentiment } from '../llmSentimentLazyLoaderLogic'
import { extractContentText } from '../sentimentUtils'
import type { llmAnalyticsSentimentLogicType } from './llmAnalyticsSentimentLogicType'

export type SentimentCategory = 'positive' | 'negative' | 'neutral'
export type SentimentFeedbackLabel = SentimentCategory

/** @deprecated Use SentimentCategory with activeFilters set instead */
export type SentimentFilterLabel = SentimentCategory | 'both'

export interface SentimentGeneration {
    uuid: string
    traceId: string
    aiInput: unknown
    model: string | null
    distinctId: string
    timestamp: string
    /** Earliest event in the trace — used for trace deep-links (matches trace createdAt) */
    createdAt: string
}

/** A generation paired with the index of the best matching message for display */
export interface SentimentCard {
    generation: SentimentGeneration
    /** Index into the generation's user messages array for the highest-intensity matching message */
    messageIndex: number
    sentiment: MessageSentiment
}

/** Multiple cards with the same user message text, collapsed into a single row */
export interface GroupedSentimentCard {
    /** Representative card (first/most recent occurrence) */
    card: SentimentCard
    /** Number of distinct traces with this same message */
    traceCount: number
}

export interface LLMAnalyticsSentimentLogicProps {
    tabId?: string
}

const GENERATIONS_PAGE_SIZE = 200
/** Stop auto-loading once we have at least this many visible cards */
const MIN_VISIBLE_CARDS = 50
/** Cap how many extra pages we fetch automatically to avoid runaway API calls */
const MAX_AUTO_LOAD_ROUNDS = 3
// Match backend MAX_MESSAGE_CHARS (2000) so training data captures the same text window the model classified
export const CLASSIFIER_WINDOW = 2000
/** Number of other visible cards to sample as negative (impressed) examples per engagement */
const IMPRESSION_SAMPLE_SIZE = 5

/** Parse aiInput and return the raw content text for the message at the given index, or '' on failure */
function getRawMessageText(aiInput: unknown, messageIndex: number): string {
    try {
        const parsed = typeof aiInput === 'string' ? JSON.parse(aiInput) : aiInput
        if (!Array.isArray(parsed)) {
            return ''
        }
        return extractContentText(parsed[messageIndex]?.content)
    } catch {
        return ''
    }
}

function getCardMessageText(card: SentimentCard): string {
    const text = getRawMessageText(card.generation.aiInput, card.messageIndex).trim()
    // Group by the same trailing window the classifier processes so messages
    // that differ only in a prefix (e.g. varying system prompt headers) are
    // correctly treated as duplicates.
    return text.slice(-CLASSIFIER_WINDOW)
}

function getSnippetFromCard(card: SentimentCard): string {
    return getRawMessageText(card.generation.aiInput, card.messageIndex).slice(-CLASSIFIER_WINDOW)
}

/** Fisher-Yates shuffle on a copy, return first n elements */
function sampleCards(cards: GroupedSentimentCard[], n: number): GroupedSentimentCard[] {
    if (cards.length <= n) {
        return cards
    }
    const shuffled = [...cards]
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
    }
    return shuffled.slice(0, n)
}

function cardKey(card: SentimentCard): string {
    return `${card.generation.uuid}:${card.messageIndex}`
}

function captureEngagementEvents(
    engagementType: 'expanded' | 'trace_clicked',
    card: SentimentCard,
    allVisibleCards: GroupedSentimentCard[],
    activeFilters: Set<SentimentCategory>,
    intensityThreshold: number
): void {
    const interactionId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    const engagedKey = cardKey(card)
    const cardPosition = allVisibleCards.findIndex((g) => cardKey(g.card) === engagedKey)
    const sentimentFilterValue = Array.from(activeFilters).sort().join(',')

    // Positive example: the card the user engaged with
    posthog.capture('llma sentiment card engaged', {
        interaction_id: interactionId,
        engagement_type: engagementType,
        generation_uuid: card.generation.uuid,
        trace_id: card.generation.traceId,
        message_index: card.messageIndex,
        message_text_snippet: getSnippetFromCard(card),
        model_prediction_label: card.sentiment.label,
        model_prediction_score: card.sentiment.score,
        ai_model: card.generation.model,
        sentiment_filter: sentimentFilterValue,
        intensity_threshold: intensityThreshold,
        card_position: cardPosition,
        visible_card_count: allVisibleCards.length,
    })

    // Negative examples: sample of other visible cards not interacted with
    const otherCards = allVisibleCards.filter((g) => cardKey(g.card) !== engagedKey)
    const sampled = sampleCards(otherCards, IMPRESSION_SAMPLE_SIZE)
    for (const { card: impressedCard } of sampled) {
        const impressedPosition = allVisibleCards.findIndex((g) => cardKey(g.card) === cardKey(impressedCard))
        posthog.capture('llma sentiment card impressed', {
            interaction_id: interactionId,
            generation_uuid: impressedCard.generation.uuid,
            trace_id: impressedCard.generation.traceId,
            message_index: impressedCard.messageIndex,
            message_text_snippet: getSnippetFromCard(impressedCard),
            model_prediction_label: impressedCard.sentiment.label,
            model_prediction_score: impressedCard.sentiment.score,
            ai_model: impressedCard.generation.model,
            card_position: impressedPosition,
            sentiment_filter: sentimentFilterValue,
            intensity_threshold: intensityThreshold,
            trigger_event: engagementType,
            trigger_generation_uuid: card.generation.uuid,
        })
    }
}

interface GenerationsQueryValues {
    dateFilter: { dateFrom: string | null; dateTo: string | null }
    shouldFilterTestAccounts: boolean
    propertyFilters: unknown[]
}

// Tracks the raw (pre-dedup) count from the last loadMoreGenerations fetch,
// so the listener can determine hasMore accurately despite deduplication.
let lastRawFetchCount = 0

async function fetchGenerations(values: GenerationsQueryValues, cursor: string | null): Promise<SentimentGeneration[]> {
    // Routed through `LLMAnalyticsSentimentViewSet.generations` which wraps
    // `execute_with_ai_events_fallback`. This keeps the read on the standard
    // kill-switch / fallback / `ai_query_source` tagging contract for the
    // rollout. Response shape is tuple-positional ([uuid, trace_id, ai_input,
    // model, distinct_id, timestamp, created_at]) — the generated wrapper
    // types `results` as `unknown[][]` so the position casts here are
    // unavoidable until the response serializer declares per-element types.
    const response = await llmAnalyticsSentimentGenerationsCreate(String(getCurrentTeamId()), {
        filters: {
            dateRange: {
                date_from: values.dateFilter.dateFrom || null,
                date_to: cursor || values.dateFilter.dateTo || null,
            },
            filterTestAccounts: values.shouldFilterTestAccounts,
            properties: values.propertyFilters,
        },
    })

    return (response.results || []).map((row: unknown[]) => ({
        uuid: row[0] as string,
        traceId: row[1] as string,
        aiInput: row[2],
        model: row[3] as string | null,
        distinctId: row[4] as string,
        timestamp: row[5] as string,
        createdAt: row[6] as string,
    }))
}

export const llmAnalyticsSentimentLogic = kea<llmAnalyticsSentimentLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsSentimentLogic']),
    key((props: LLMAnalyticsSentimentLogicProps) => props.tabId || 'default'),
    props({} as LLMAnalyticsSentimentLogicProps),
    connect((props: LLMAnalyticsSentimentLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters', 'activeTab'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            llmGenerationSentimentLazyLoaderLogic,
            ['sentimentByGenerationId'],
        ],
        actions: [llmGenerationSentimentLazyLoaderLogic, ['ensureGenerationSentimentLoaded']],
    })),

    actions({
        activate: true,
        /** @deprecated Use toggleSentimentCategory instead */
        setSentimentFilter: (sentimentFilter: SentimentFilterLabel) => ({ sentimentFilter }),
        toggleSentimentCategory: (category: SentimentCategory) => ({ category }),
        setIntensityThreshold: (intensityThreshold: number) => ({ intensityThreshold }),
        toggleCardExpanded: (cardKey: string) => ({ cardKey }),
        loadMoreGenerations: true,
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        trackTraceClicked: (card: SentimentCard) => ({ card }),
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
        activeFilters: [
            new Set<SentimentCategory>(['positive', 'negative']) as Set<SentimentCategory>,
            {
                toggleSentimentCategory: (state, { category }) => {
                    const next = new Set(state)
                    if (next.has(category)) {
                        // Don't allow deselecting all — keep at least one
                        if (next.size > 1) {
                            next.delete(category)
                        }
                    } else {
                        next.add(category)
                    }
                    return next
                },
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
                toggleCardExpanded: (state, { cardKey }) => {
                    const newSet = new Set(state)
                    if (newSet.has(cardKey)) {
                        newSet.delete(cardKey)
                    } else {
                        newSet.add(cardKey)
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
        autoLoadRounds: [
            0 as number,
            {
                loadGenerations: () => 0,
                loadMoreGenerations: (state: number) => state + 1,
            },
        ],
        hasLoadedOnce: [
            false as boolean,
            {
                loadGenerations: () => true,
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
                    lastRawFetchCount = newGenerations.length
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
            (s) => [s.generations, s.sentimentByGenerationId, s.activeFilters, s.intensityThreshold],
            (
                generations: SentimentGeneration[],
                sentimentByGenerationId: Record<string, GenerationSentiment | null>,
                activeFilters: Set<SentimentCategory>,
                intensityThreshold: number
            ): SentimentCard[] => {
                const cards: SentimentCard[] = []
                for (const gen of generations) {
                    const sentimentData = sentimentByGenerationId[gen.uuid]
                    if (!sentimentData?.messages) {
                        continue
                    }

                    // Find the best card per active category per generation
                    const best: Record<string, { index: number; score: number; sentiment: MessageSentiment }> = {}

                    for (const [idx, msg] of Object.entries(sentimentData.messages)) {
                        if (!activeFilters.has(msg.label as SentimentCategory)) {
                            continue
                        }
                        // For neutral messages, skip the intensity threshold — neutral scores are
                        // inherently lower and the threshold is designed for positive/negative signals
                        if (msg.label !== 'neutral' && msg.score < intensityThreshold) {
                            continue
                        }
                        const prev = best[msg.label]
                        if (!prev || msg.score > prev.score) {
                            best[msg.label] = { index: Number(idx), score: msg.score, sentiment: msg }
                        }
                    }

                    for (const { index, sentiment } of Object.values(best)) {
                        cards.push({ generation: gen, messageIndex: index, sentiment })
                    }
                }
                return cards
            },
        ],
        /** Counts of displayable cards per sentiment category (best-per-generation, matching sentimentCards logic) */
        sentimentSummary: [
            (s) => [s.generations, s.sentimentByGenerationId, s.intensityThreshold],
            (
                generations: SentimentGeneration[],
                sentimentByGenerationId: Record<string, GenerationSentiment | null>,
                intensityThreshold: number
            ): Record<SentimentCategory, number> => {
                const counts: Record<SentimentCategory, number> = { positive: 0, negative: 0, neutral: 0 }
                for (const gen of generations) {
                    const sentimentData = sentimentByGenerationId[gen.uuid]
                    if (!sentimentData?.messages) {
                        continue
                    }
                    // Use the same best-per-category-per-generation logic as sentimentCards
                    const best: Partial<Record<SentimentCategory, number>> = {}
                    for (const msg of Object.values(sentimentData.messages)) {
                        const label = msg.label as SentimentCategory
                        if (!(label in counts)) {
                            continue
                        }
                        if (label !== 'neutral' && msg.score < intensityThreshold) {
                            continue
                        }
                        const prev = best[label]
                        if (prev === undefined || msg.score > prev) {
                            best[label] = msg.score
                        }
                    }
                    for (const label of Object.keys(best) as SentimentCategory[]) {
                        counts[label]++
                    }
                }
                return counts
            },
        ],
        groupedSentimentCards: [
            (s) => [s.sentimentCards],
            (cards: SentimentCard[]): GroupedSentimentCard[] => {
                const groups = new Map<string, { grouped: GroupedSentimentCard; traceIds: Set<string> }>()
                const result: GroupedSentimentCard[] = []

                for (const card of cards) {
                    const text = getCardMessageText(card)
                    // Empty/unparseable messages get a unique key so they're never grouped
                    const key = text || `__unique__${card.generation.uuid}:${card.messageIndex}`
                    const existing = groups.get(key)
                    if (existing) {
                        existing.traceIds.add(card.generation.traceId)
                        existing.grouped.traceCount = existing.traceIds.size
                    } else {
                        const grouped: GroupedSentimentCard = {
                            card,
                            traceCount: 1,
                        }
                        groups.set(key, { grouped, traceIds: new Set([card.generation.traceId]) })
                        result.push(grouped)
                    }
                }

                return result
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
        return {
            activate: () => {
                if (!values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            loadGenerationsSuccess: ({ generations }) => {
                actions.setHasMore(generations.length >= GENERATIONS_PAGE_SIZE)
                for (const gen of generations) {
                    if (values.sentimentByGenerationId[gen.uuid] === undefined) {
                        actions.ensureGenerationSentimentLoaded(gen.uuid, values.dateFilter)
                    }
                }
            },
            loadMoreGenerationsSuccess: () => {
                actions.setHasMore(lastRawFetchCount >= GENERATIONS_PAGE_SIZE)
                for (const gen of values.generations) {
                    if (values.sentimentByGenerationId[gen.uuid] === undefined) {
                        actions.ensureGenerationSentimentLoaded(gen.uuid, values.dateFilter)
                    }
                }
            },
            toggleCardExpanded: ({ cardKey: key }) => {
                // Only track when expanding (key is now in the set), not collapsing
                if (!values.expandedCardIds.has(key)) {
                    return
                }
                const group = values.groupedSentimentCards.find((g) => cardKey(g.card) === key)
                if (!group) {
                    return
                }
                captureEngagementEvents(
                    'expanded',
                    group.card,
                    values.groupedSentimentCards,
                    values.activeFilters,
                    values.intensityThreshold
                )
            },
            trackTraceClicked: ({ card }) => {
                captureEngagementEvents(
                    'trace_clicked',
                    card,
                    values.groupedSentimentCards,
                    values.activeFilters,
                    values.intensityThreshold
                )
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

    subscriptions(({ actions, values }) => {
        let wasAnalyzing = false

        return {
            activeTab: (activeTab) => {
                if (activeTab === 'sentiment') {
                    actions.activate()
                }
            },
            dateFilter: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            shouldFilterTestAccounts: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            propertyFilters: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            stillAnalyzing: (stillAnalyzing: boolean) => {
                if (wasAnalyzing && !stillAnalyzing && values.activeTab === 'sentiment') {
                    const totalGenerations = values.generations.length
                    const failedCount = values.generations.filter(
                        (gen) => values.sentimentByGenerationId[gen.uuid] === null
                    ).length
                    const cardCount = values.sentimentCards.length
                    const visibleCards = values.groupedSentimentCards.length

                    // Auto-load more generations if we don't have enough visible cards
                    const shouldAutoLoad =
                        visibleCards < MIN_VISIBLE_CARDS &&
                        values.hasMore &&
                        values.autoLoadRounds < MAX_AUTO_LOAD_ROUNDS

                    if ((totalGenerations === 0 || cardCount === 0) && !shouldAutoLoad) {
                        posthog.capture('llma sentiment empty state', {
                            reason:
                                totalGenerations === 0
                                    ? 'no_generations'
                                    : failedCount === totalGenerations
                                      ? 'all_classification_failed'
                                      : 'no_matching_cards',
                            total_generations: totalGenerations,
                            failed_classifications: failedCount,
                            sentiment_filter: Array.from(values.activeFilters).sort().join(','),
                            intensity_threshold: values.intensityThreshold,
                        })
                    }

                    if (shouldAutoLoad) {
                        actions.loadMoreGenerations()
                    }
                }
                wasAnalyzing = stillAnalyzing
            },
        }
    }),
])
