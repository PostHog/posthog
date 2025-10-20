import { connect, kea, path, props, selectors } from 'kea'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyResponseType,
    DataTableNode,
    LLMTrace,
    LLMTraceEvent,
    TraceQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { llmAnalyticsTraceDataLogicType } from './llmAnalyticsTraceDataLogicType'
import { llmAnalyticsTraceLogic } from './llmAnalyticsTraceLogic'
import {
    SearchOccurrence,
    eventMatchesSearch,
    findMessageOccurrences,
    findSidebarOccurrences,
    findTraceOccurrences,
} from './searchUtils'
import { formatLLMUsage, getEventType, isLLMEvent, normalizeMessages } from './utils'

export interface TraceDataLogicProps {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
    searchQuery: string
}

function getDataNodeLogicProps({ traceId, query, cachedResults }: TraceDataLogicProps): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Trace.${traceId}`,
        dataNodeCollectionId: traceId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: traceId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

const FEEDBACK_EVENTS = new Set(['$ai_feedback', '$ai_metric'])

/**
 * Find all parent events for a given event, including the event itself
 */
function findEventWithParents(
    targetEvent: LLMTraceEvent,
    allEvents: LLMTraceEvent[],
    traceId: string
): LLMTraceEvent[] {
    const eventMap = new Map<string, LLMTraceEvent>()

    // Build map of eventId -> event
    for (const event of allEvents) {
        const eventId = event.properties.$ai_generation_id ?? event.properties.$ai_span_id ?? event.id
        eventMap.set(eventId, event)
    }

    const parentChain: LLMTraceEvent[] = []
    let currentEvent: LLMTraceEvent | null = targetEvent

    // Walk up the parent chain
    while (currentEvent) {
        parentChain.push(currentEvent)

        const parentId: string | undefined =
            currentEvent.properties.$ai_parent_id ?? currentEvent.properties.$ai_trace_id
        if (!parentId || parentId === traceId) {
            break
        }

        currentEvent = eventMap.get(parentId) || null
    }

    return parentChain
}

export const llmAnalyticsTraceDataLogic = kea<llmAnalyticsTraceDataLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsTraceLogic']),
    props({} as TraceDataLogicProps),
    connect((props: TraceDataLogicProps) => ({
        values: [
            llmAnalyticsTraceLogic,
            ['eventId', 'searchQuery'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError'],
        ],
    })),
    selectors({
        trace: [
            (s) => [s.response],
            (response): LLMTrace | undefined => {
                const traceResponse = response as TraceQueryResponse | null
                return traceResponse?.results?.[0]
            },
        ],
        showableEvents: [
            (s) => [s.trace],
            (trace): LLMTraceEvent[] =>
                trace ? trace.events.filter((event) => !FEEDBACK_EVENTS.has(event.event)) : [],
        ],
        filteredEvents: [
            (s, p) => [s.showableEvents, s.searchQuery, p.traceId],
            (showableEvents: LLMTraceEvent[], searchQuery: string, traceId: string): LLMTraceEvent[] => {
                if (!searchQuery.trim()) {
                    return showableEvents
                }

                // Find events that match the search
                const matchingEvents = showableEvents.filter((event: LLMTraceEvent) =>
                    eventMatchesSearch(event, searchQuery)
                )

                // For each matching event, include its parent chain
                const eventsWithParents = new Set<LLMTraceEvent>()

                for (const matchingEvent of matchingEvents) {
                    const parentChain = findEventWithParents(matchingEvent, showableEvents, traceId)
                    for (const event of parentChain) {
                        eventsWithParents.add(event)
                    }
                }

                return Array.from(eventsWithParents)
            },
        ],
        filteredTree: [
            (s, p) => [p.traceId, s.trace, s.searchQuery, s.filteredEvents],
            (traceId, trace, searchQuery, filteredEvents): TraceTreeNode[] => {
                if (!searchQuery.trim()) {
                    return restoreTree(trace?.events || [], traceId)
                }
                return restoreTree(filteredEvents, traceId)
            },
        ],
        mostRelevantEvent: [
            (s) => [s.filteredEvents, s.searchQuery],
            (filteredEvents, searchQuery): LLMTraceEvent | null => {
                if (!searchQuery.trim() || !filteredEvents.length) {
                    return null
                }

                const query = searchQuery.toLowerCase().trim()

                // Score events by relevance (sort of doing a random scoring for now but i feel like this is directionally correct)
                const scoredEvents = filteredEvents.map((event) => {
                    let score = 0

                    // Higher score for generation events
                    if (event.event === '$ai_generation') {
                        score += 10
                    }

                    // Higher score for title matches
                    const title = event.properties.$ai_span_name || event.event || ''
                    if (title.toLowerCase().includes(query)) {
                        score += 5
                    }

                    // Score for model matches
                    const model = event.properties.$ai_model || ''
                    if (model.toLowerCase().includes(query)) {
                        score += 3
                    }

                    // Score for input/output content matches
                    const input = JSON.stringify(
                        event.properties.$ai_input || event.properties.$ai_input_state || ''
                    ).toLowerCase()
                    if (input.includes(query)) {
                        score += 2
                    }

                    const output = JSON.stringify(
                        event.properties.$ai_output ||
                            event.properties.$ai_output_choices ||
                            event.properties.$ai_output_state ||
                            ''
                    ).toLowerCase()
                    if (output.includes(query)) {
                        score += 2
                    }

                    return { event, score }
                })

                // Return the highest scoring event
                const best = scoredEvents.sort((a, b) => b.score - a.score)[0]
                return best?.event || null
            },
        ],
        searchOccurrences: [
            (s) => [s.showableEvents, s.searchQuery, s.trace],
            (showableEvents, searchQuery, trace): SearchOccurrence[] => {
                if (!searchQuery.trim()) {
                    return []
                }

                const query = searchQuery.toLowerCase().trim()

                // Collect occurrences from different sources
                const traceOccurrences = findTraceOccurrences(trace, query)
                const sidebarOccurrences = findSidebarOccurrences(showableEvents, query)
                const messageOccurrences = findMessageOccurrences(showableEvents, query, normalizeMessages)

                // Combine all occurrences
                return [...traceOccurrences, ...sidebarOccurrences, ...messageOccurrences]
            },
        ],
        metricEvents: [
            (s) => [s.trace],
            (trace): LLMTraceEvent[] | undefined =>
                trace?.events.filter((event) => event.event === '$ai_metric' && event.properties.$ai_metric_value),
        ],
        feedbackEvents: [
            (s) => [s.trace],
            (trace): LLMTraceEvent[] | undefined =>
                trace?.events.filter((event) => event.event === '$ai_feedback' && event.properties.$ai_feedback_text),
        ],
        metricsAndFeedbackEvents: [
            (s) => [s.metricEvents, s.feedbackEvents],
            (metricEvents, feedbackEvents): { metric: string; value: any }[] =>
                [...(metricEvents ?? []), ...(feedbackEvents ?? [])].map((event) => ({
                    metric:
                        event.event === '$ai_metric' ? (event.properties.$ai_metric_name ?? 'Metric') : 'User feedback',
                    value: event.properties.$ai_metric_value ?? event.properties.$ai_feedback_text,
                })),
        ],
        event: [
            (s, p) => [p.traceId, s.eventId, s.trace, s.showableEvents],
            (traceId, eventId, trace, showableEvents): LLMTrace | LLMTraceEvent | null => {
                if (!eventId || eventId === traceId) {
                    return trace || null
                }
                if (!showableEvents?.length) {
                    return null
                }
                return showableEvents.find((event) => event.id === eventId) || null
            },
        ],
        tree: [(s) => [s.filteredTree], (filteredTree): TraceTreeNode[] => filteredTree],
        enrichedTree: [
            (s) => [s.filteredTree],
            (filteredTree: TraceTreeNode[]): EnrichedTraceTreeNode[] => filteredTree.map(enrichNode),
        ],
        eventMetadata: [
            (s) => [s.event],
            (event): Record<string, unknown> | undefined => {
                if (event && isLLMEvent(event)) {
                    // Filter out all system properties as they're typically useless for datasets.
                    return Object.fromEntries(Object.entries(event.properties).filter(([key]) => !key.startsWith('$')))
                }
                return undefined
            },
        ],
        availableEventTypes: [
            (s) => [s.enrichedTree],
            (enrichedTree: EnrichedTraceTreeNode[]): string[] => {
                const types = new Set<string>()
                const addTypesFromTree = (nodes: EnrichedTraceTreeNode[]): void => {
                    for (const node of nodes) {
                        types.add(getEventType(node.event))
                        if (node.children) {
                            addTypesFromTree(node.children)
                        }
                    }
                }
                addTypesFromTree(enrichedTree)
                types.delete('trace')
                return [...types]
            },
        ],
    }),
])

export interface TraceTreeNode {
    event: LLMTraceEvent
    children?: TraceTreeNode[]
    aggregation?: SpanAggregation
}

export interface EnrichedTraceTreeNode extends TraceTreeNode {
    children?: EnrichedTraceTreeNode[]
    displayTotalCost: number
    displayLatency: number
    displayUsage: string | null
}

export interface SpanAggregation {
    totalCost: number
    totalLatency: number
    inputTokens: number
    outputTokens: number
    hasGenerationChildren: boolean
}

function extractTotalCost(event: LLMTraceEvent): number {
    return event.properties.$ai_total_cost_usd || 0
}

function extractLatency(event: LLMTraceEvent): number {
    return event.properties.$ai_latency || 0
}

function enrichNode(node: TraceTreeNode): EnrichedTraceTreeNode {
    return {
        ...node,
        children: node.children?.map(enrichNode),
        displayTotalCost: node.aggregation?.totalCost ?? extractTotalCost(node.event),
        displayLatency: node.aggregation?.totalLatency ?? extractLatency(node.event),
        displayUsage: node.aggregation ? formatLLMUsage(node.aggregation) : formatLLMUsage(node.event),
    }
}

function aggregateSpanMetrics(node: TraceTreeNode): SpanAggregation {
    const event = node.event
    let hasGenerationChildren = false

    // Use direct values if available, otherwise start with 0 for aggregation
    let totalCost = event.properties.$ai_total_cost_usd ?? 0
    let totalLatency = event.properties.$ai_latency ?? 0
    let inputTokens = event.properties.$ai_input_tokens ?? 0
    let outputTokens = event.properties.$ai_output_tokens ?? 0

    // Only aggregate from children if parent doesn't have direct values
    const shouldAggregateCost = event.properties.$ai_total_cost_usd === undefined
    const shouldAggregateLatency = event.properties.$ai_latency === undefined
    const shouldAggregateInputTokens = event.properties.$ai_input_tokens === undefined
    const shouldAggregateOutputTokens = event.properties.$ai_output_tokens === undefined

    if (node.children && node.children.length > 0) {
        for (const child of node.children) {
            if (child.event.event === '$ai_generation') {
                hasGenerationChildren = true
            }

            // Use aggregated metrics if child has children, otherwise use direct metrics
            if (child.children && child.children.length > 0) {
                const childAgg = aggregateSpanMetrics(child)
                if (shouldAggregateCost) {
                    totalCost += childAgg.totalCost
                }
                if (shouldAggregateLatency) {
                    totalLatency += childAgg.totalLatency
                }
                if (shouldAggregateInputTokens) {
                    inputTokens += childAgg.inputTokens
                }
                if (shouldAggregateOutputTokens) {
                    outputTokens += childAgg.outputTokens
                }
                if (childAgg.hasGenerationChildren) {
                    hasGenerationChildren = true
                }
            } else {
                // Child has no children, use its direct metrics
                if (shouldAggregateCost) {
                    totalCost += child.event.properties.$ai_total_cost_usd || 0
                }
                if (shouldAggregateLatency) {
                    totalLatency += child.event.properties.$ai_latency || 0
                }
                if (shouldAggregateInputTokens) {
                    inputTokens += child.event.properties.$ai_input_tokens || 0
                }
                if (shouldAggregateOutputTokens) {
                    outputTokens += child.event.properties.$ai_output_tokens || 0
                }
            }
        }
    }

    return { totalCost, totalLatency, inputTokens, outputTokens, hasGenerationChildren }
}

// Export the parent chain function for testing
export { findEventWithParents }

export function restoreTree(events: LLMTraceEvent[], traceId: string): TraceTreeNode[] {
    const childrenMap = new Map<any, any[]>()
    const idMap = new Map<any, LLMTraceEvent>()
    const visitedNodes = new Set<any>()

    for (const event of events) {
        if (FEEDBACK_EVENTS.has(event.event)) {
            continue
        }

        const eventId = event.properties.$ai_generation_id ?? event.properties.$ai_span_id ?? event.id
        idMap.set(eventId, event)

        const parentId = event.properties.$ai_parent_id ?? event.properties.$ai_trace_id

        if (parentId !== undefined && parentId !== null) {
            const existingEvents = childrenMap.get(parentId)
            if (existingEvents) {
                existingEvents.push(eventId)
            } else {
                childrenMap.set(parentId, [eventId])
            }
        }
    }

    function traverse(spanId: any): TraceTreeNode | null {
        if (visitedNodes.has(spanId)) {
            console.warn('Circular reference detected in trace tree:', spanId)
            return null
        }

        const event = idMap.get(spanId)
        if (!event) {
            return null
        }

        visitedNodes.add(spanId)
        const children = childrenMap.get(spanId)
        const result: TraceTreeNode = {
            event,
            children: children?.map((child) => traverse(child)).filter((node): node is TraceTreeNode => node !== null),
        }

        if (result.children && result.children.length > 0 && event.event !== '$ai_generation') {
            result.aggregation = aggregateSpanMetrics(result)
        }

        visitedNodes.delete(spanId)
        return result
    }

    const directChildren = childrenMap.get(traceId) || []
    return directChildren.map((childId) => traverse(childId)).filter((node): node is TraceTreeNode => node !== null)
}
