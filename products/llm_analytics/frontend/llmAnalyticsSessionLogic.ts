import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps, PropertyFilterType } from '~/types'

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
            (sessionId, dateRange): DataTableNode => {
                const tracesQuery: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    dateRange: dateRange?.dateFrom
                        ? {
                              date_from: dateRange.dateFrom,
                              date_to: dateRange?.dateTo || dayjs(dateRange.dateFrom).add(30, 'days').toISOString(),
                          }
                        : {
                              date_from: dayjs.utc(new Date(2025, 0, 10)).toISOString(),
                          },
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
            (s) => [s.sessionId],
            (sessionId): Breadcrumb[] => {
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
                        path: urls.llmAnalyticsSessions(),
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

    urlToAction(({ actions }) => ({
        [urls.llmAnalyticsSession(':id')]: ({ id }, { timestamp }) => {
            actions.setSessionId(id ?? '')
            if (timestamp) {
                actions.setDateRange(timestamp || null)
            }
        },
    })),
])
