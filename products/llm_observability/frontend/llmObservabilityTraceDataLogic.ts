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
            ['eventId'],
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
        tree: [
            (s, p) => [p.traceId, s.trace],
            (traceId, trace): TraceTreeNode[] => restoreTree(trace?.events || [], traceId),
        ],
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
