import { connect, kea, path, props, selectors } from 'kea'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyResponseType,
    DataTableNode,
    LLMTrace,
    LLMTraceEvent,
    TracesQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { llmObservabilityTraceDataLogicType } from './llmObservabilityTraceDataLogicType'
import { llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'

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

export const llmObservabilityTraceDataLogic = kea<llmObservabilityTraceDataLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityTraceLogic']),
    props({} as TraceDataLogicProps),
    connect((props: TraceDataLogicProps) => ({
        values: [
            llmObservabilityTraceLogic,
            ['eventId', 'searchQuery'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError'],
        ],
    })),
    selectors({
        trace: [
            (s) => [s.response],
            (response): LLMTrace | undefined => {
                const traceResponse = response as TracesQueryResponse | null
                return traceResponse?.results?.[0]
            },
        ],
        showableEvents: [
            (s) => [s.trace],
            (trace): LLMTraceEvent[] =>
                trace ? trace.events.filter((event) => !FEEDBACK_EVENTS.has(event.event)) : [],
        ],
        filteredEvents: [
            (s) => [s.showableEvents, s.searchQuery],
            (showableEvents, searchQuery): LLMTraceEvent[] => {
                if (!searchQuery.trim()) {
                    return showableEvents
                }

                const query = searchQuery.toLowerCase().trim()
                return showableEvents.filter((event) => {
                    // Search in event title
                    const title = event.properties.$ai_span_name || event.event || ''
                    if (title.toLowerCase().includes(query)) {
                        return true
                    }

                    // Search in model name
                    const model = event.properties.$ai_model || ''
                    if (model.toLowerCase().includes(query)) {
                        return true
                    }

                    // Search in provider
                    const provider = event.properties.$ai_provider || ''
                    if (provider.toLowerCase().includes(query)) {
                        return true
                    }

                    // Search in input content
                    const input = JSON.stringify(
                        event.properties.$ai_input || event.properties.$ai_input_state || ''
                    ).toLowerCase()
                    if (input.includes(query)) {
                        return true
                    }

                    // Search in output content
                    const output = JSON.stringify(
                        event.properties.$ai_output ||
                            event.properties.$ai_output_choices ||
                            event.properties.$ai_output_state ||
                            ''
                    ).toLowerCase()
                    if (output.includes(query)) {
                        return true
                    }

                    // Search in error messages
                    const error = JSON.stringify(event.properties.$ai_error || '').toLowerCase()
                    if (error.includes(query)) {
                        return true
                    }

                    return false
                })
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
                        event.event === '$ai_metric' ? event.properties.$ai_metric_name ?? 'Metric' : 'User feedback',
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
    }),
])

export interface TraceTreeNode {
    event: LLMTraceEvent
    children?: TraceTreeNode[]
}

export function restoreTree(events: LLMTraceEvent[], traceId: string): TraceTreeNode[] {
    const childrenMap = new Map<any, any[]>()
    const idMap = new Map<any, LLMTraceEvent>()
    const visitedNodes = new Set<any>()

    // Map all events with parents to their parent IDs
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
        const result = {
            event,
            children: children?.map((child) => traverse(child)).filter((node): node is TraceTreeNode => node !== null),
        }
        visitedNodes.delete(spanId)
        return result
    }

    // Get all direct children of the trace ID
    const directChildren = childrenMap.get(traceId) || []
    return directChildren.map((childId) => traverse(childId)).filter((node): node is TraceTreeNode => node !== null)
}
