import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps, PropertyFilterType } from '~/types'

import { llmAnalyticsLogic } from './llmAnalyticsLogic'
import type { llmAnalyticsSessionLogicType } from './llmAnalyticsSessionLogicType'

export interface LLMAnalyticsSessionDataNodeLogicParams {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

export function getDataNodeLogicProps({
    sessionId,
    query,
    cachedResults,
}: LLMAnalyticsSessionDataNodeLogicParams): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${sessionId}`,
        dataNodeCollectionId: sessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: sessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmAnalyticsSessionLogic = kea<llmAnalyticsSessionLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsSessionLogic']),

    connect({
        values: [llmAnalyticsLogic, ['dateFilter']],
    }),

    actions({
        setSessionId: (sessionId: string) => ({ sessionId }),
        setDateRange: (dateFrom: string | null, dateTo?: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        sessionId: ['' as string, { setSessionId: (_, { sessionId }) => sessionId }],
        dateRange: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({
                    dateFrom: dateFrom ?? null,
                    dateTo: dateTo ?? null,
                }),
            },
        ],
    }),

    selectors({
        query: [
            (s) => [s.sessionId, s.dateRange],
            (
                sessionId: string,
                dateRange: { dateFrom: string | null; dateTo: string | null } | null
            ): DataTableNode => {
                const tracesQuery: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    dateRange: dateRange?.dateFrom
                        ? {
                              date_from: dateRange.dateFrom,
                              date_to: dateRange?.dateTo || undefined,
                          }
                        : undefined,
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$ai_session_id',
                            operator: 'exact' as any,
                            value: sessionId,
                        },
                    ],
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: tracesQuery,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.sessionId, s.dateFilter],
            (sessionId: string, dateFilter: { dateFrom: string | null; dateTo: string | null }): Breadcrumb[] => {
                const sessionsUrl = urls.llmAnalyticsSessions()
                const searchParams = router.values.searchParams
                const sessionsPath =
                    dateFilter?.dateFrom || dateFilter?.dateTo || Object.keys(searchParams).length > 0
                        ? `${sessionsUrl}?${new URLSearchParams({
                              ...searchParams,
                              ...(dateFilter?.dateFrom && { date_from: dateFilter.dateFrom }),
                              ...(dateFilter?.dateTo && { date_to: dateFilter.dateTo }),
                          }).toString()}`
                        : sessionsUrl
                return [
                    {
                        key: 'LLMAnalytics',
                        name: 'LLM analytics',
                        path: urls.llmAnalyticsDashboard(),
                        iconType: 'llm_analytics',
                    },
                    {
                        key: 'LLMAnalyticsSessions',
                        name: 'Sessions',
                        path: sessionsPath,
                        iconType: 'llm_analytics',
                    },
                    {
                        key: ['LLMAnalyticsSession', sessionId || ''],
                        name: sessionId,
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsSession(':id')]: ({ id }, { timestamp, date_from, date_to }) => {
            actions.setSessionId(id ?? '')
            if (timestamp) {
                actions.setDateRange(timestamp || null)
            } else if (date_from || date_to) {
                actions.setDateRange(date_from || null, date_to || null)
            } else if (values.dateRange?.dateFrom) {
                // Keep existing date range if no params provided
                actions.setDateRange(values.dateRange.dateFrom, values.dateRange.dateTo || null)
            } else if (values.dateFilter) {
                // Fall back to parent dateFilter when navigating without explicit date params
                actions.setDateRange(values.dateFilter.dateFrom, values.dateFilter.dateTo)
            }
        },
    })),
])
