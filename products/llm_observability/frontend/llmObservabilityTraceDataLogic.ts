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
            (trace): LLMTraceEvent[] | undefined => trace?.events.filter((event) => event.event !== '$ai_metric'),
        ],
        metrics: [
            (s) => [s.trace],
            (trace): LLMTraceEvent[] | undefined => trace?.events.filter((event) => event.event === '$ai_metric'),
        ],
        event: [
            (s) => [s.eventId, s.showableEvents],
            (eventId, showableEvents): LLMTraceEvent | undefined => {
                if (!showableEvents) {
                    return undefined
                }
                return eventId ? showableEvents.find((event) => event.id === eventId) : showableEvents[0]
            },
        ],
    }),
])
