import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TracesQuery, TracesQueryResponse } from '~/queries/schema'
import { Breadcrumb, InsightLogicProps } from '~/types'

import type { llmObservabilityTraceLogicType } from './llmObservabilityTraceLogicType'

export interface LLMObservabilityTraceDataNodeLogicParams {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

export function getDataNodeLogicProps({
    traceId,
    query,
    cachedResults,
}: LLMObservabilityTraceDataNodeLogicParams): DataNodeLogicProps {
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

export const llmObservabilityTraceLogic = kea<llmObservabilityTraceLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityTraceLogic']),

    connect(() => ({
        values: [
            dataNodeLogic({ key: 'InsightViz.new-AdHoc.DataNode.llm-observability-traces' } as DataNodeLogicProps),
            ['response as cachedTracesResults'],
        ],
    })),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        dateFrom: [null as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
    }),

    selectors({
        query: [
            (s) => [s.traceId, s.dateFrom],
            (traceId, dateFrom): DataTableNode => {
                const tracesQuery: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    traceId,
                    dateRange: dateFrom
                        ? // dateFrom is a minimum timestamp of an event for a trace.
                          {
                              date_from: dateFrom,
                              date_to: dayjs(dateFrom).add(10, 'minutes').toISOString(),
                          }
                        : // By default will look for traces from the beginning.
                          {
                              date_from: dayjs.utc(new Date(2025, 0, 10)).toISOString(),
                          },
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: tracesQuery,
                }
            },
        ],
        cachedTraceResponse: [
            (s) => [s.cachedTracesResults, s.traceId],
            (cachedTracesResults, traceId) => {
                if (!cachedTracesResults) {
                    return null
                }
                const response = cachedTracesResults as TracesQueryResponse

                return {
                    ...response,
                    results: response.results.filter((trace) => trace.id === traceId),
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.traceId],
            (traceId): Breadcrumb[] => {
                return [
                    {
                        key: 'LLMObservability',
                        name: 'Traces',
                        path: urls.llmObservability('traces'),
                    },
                    {
                        key: ['LLMObservability', traceId || ''],
                        name: traceId,
                    },
                ]
            },
        ],
    }),

    urlToAction(({ actions }) => ({
        [urls.llmObservabilityTrace(':id')]: ({ id }, { event, timestamp }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
            actions.setDateFrom(timestamp || null)
        },
    })),
])
