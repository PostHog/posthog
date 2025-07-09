import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
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
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmObservabilityTraceLogic = kea<llmObservabilityTraceLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityTraceLogic']),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
        setIsRenderingMarkdown: (isRenderingMarkdown: boolean) => ({ isRenderingMarkdown }),
        toggleMarkdownRendering: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        dateFrom: [null as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        searchQuery: ['' as string, { setSearchQuery: (_, { searchQuery }) => searchQuery }],
        isRenderingMarkdown: [
            true as boolean,
            {
                setIsRenderingMarkdown: (_, { isRenderingMarkdown }) => isRenderingMarkdown,
                toggleMarkdownRendering: (state) => !state,
            },
        ],
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

        breadcrumbs: [
            (s) => [s.traceId],
            (traceId): Breadcrumb[] => {
                return [
                    {
                        key: 'LLMObservability',
                        name: 'LLM observability',
                        path: urls.llmObservabilityDashboard(),
                    },
                    {
                        key: 'LLMObservabilityTraces',
                        name: 'Traces',
                        path: urls.llmObservabilityTraces(),
                    },
                    {
                        key: ['LLMObservabilityTrace', traceId || ''],
                        name: traceId,
                    },
                ]
            },
        ],
    }),

    listeners(({ values }) => ({
        setIsRenderingMarkdown: ({ isRenderingMarkdown }) => {
            localStorage.setItem('llm-observability-markdown-rendering', JSON.stringify(isRenderingMarkdown))
        },
        toggleMarkdownRendering: () => {
            localStorage.setItem('llm-observability-markdown-rendering', JSON.stringify(values.isRenderingMarkdown))
        },
    })),

    afterMount(({ actions }) => {
        const savedState = localStorage.getItem('llm-observability-markdown-rendering')
        if (savedState !== null) {
            try {
                const isRenderingMarkdown = JSON.parse(savedState)
                actions.setIsRenderingMarkdown(isRenderingMarkdown)
            } catch {
                // If parsing fails, keep the default value
            }
        }
    }),

    urlToAction(({ actions }) => ({
        [urls.llmObservabilityTrace(':id')]: ({ id }, { event, timestamp }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
            actions.setDateFrom(timestamp || null)
        },
    })),
])
