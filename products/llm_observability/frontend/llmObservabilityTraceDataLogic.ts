import { connect, kea, path, props, selectors } from 'kea'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, LLMTrace, LLMTraceEvent, TracesQueryResponse } from '~/queries/schema'
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
        alwaysRefresh: false,
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
    }),
])
