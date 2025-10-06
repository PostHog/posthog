import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { dateStringToDayJs } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { Breadcrumb, ChartDisplayType, InsightLogicProps } from '~/types'

import {
    EndpointsUsageQueryTile,
    EndpointsUsageTileId,
    INITIAL_DATE_FROM,
    INITIAL_DATE_TO,
    INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED,
} from './common'
import type { endpointsUsageLogicType } from './endpointsUsageLogicType'
import {
    createApiCpuSecondsQuery,
    createApiQueriesCountQuery,
    createApiQueriesPerKeyQuery,
    createApiReadTbQuery,
    createExpensiveQueriesColumns,
    createExpensiveQueriesQuery,
    createFailedQueriesColumns,
    createFailedQueriesQuery,
    createLast20QueriesColumns,
    createLast20QueriesQuery,
} from './queries'

export interface EndpointsUsageLogicProps {
    tabId: string
}

export const endpointsUsageLogic = kea<endpointsUsageLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointsUsageLogic']),
    props({} as EndpointsUsageLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        values: [sceneLogic, ['sceneKey']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setRequestNameFilter: (requestNameFilter: string[]) => ({ requestNameFilter }),
        setRequestNameBreakdownEnabled: (requestNameBreakdownEnabled: boolean) => ({ requestNameBreakdownEnabled }),
        setSearch: (search: string) => ({ search }),
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            } as { dateFrom: string | null; dateTo: string | null },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
        requestNameFilter: [
            [] as string[],
            {
                setRequestNameFilter: (_, { requestNameFilter }) => requestNameFilter,
            },
        ],
        requestNameBreakdownEnabled: [
            INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED as boolean,
            {
                setRequestNameBreakdownEnabled: (_, { requestNameBreakdownEnabled }) => requestNameBreakdownEnabled,
            },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
    }),

    loaders({
        requestNames: [
            [] as string[],
            {
                loadRequestNames: async () => {
                    const query = hogql`
                        SELECT DISTINCT name
                        FROM query_log
                        WHERE is_personal_api_key_request
                            AND name IS NOT NULL
                            AND name != ''
                        ORDER BY name ASC
                    `

                    const response = await api.queryHogQL(query, {
                        refresh: 'force_blocking',
                    })

                    return response.results?.map((row: string[]) => row[0]) || []
                },
            },
        ],
    }),

    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey: string) => {
                if (sceneKey === 'endpointsUsage') {
                    return 'usage'
                }
                return 'endpoints'
            },
        ],
        tiles: [
            (s) => [s.dateFilter, s.requestNameBreakdownEnabled, s.requestNameFilter, s.activeTab],
            (dateFilter, requestNameBreakdownEnabled, requestNameFilter, activeTab): EndpointsUsageQueryTile[] => {
                if (activeTab === 'endpoints') {
                    return []
                }

                const dateFromDayjs = dateStringToDayJs(dateFilter.dateFrom)
                const dateToDayjs = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo) : null

                const dateFrom = dateFromDayjs
                    ? dateFromDayjs.format('YYYY-MM-DD')
                    : dayjs().subtract(7, 'day').format('YYYY-MM-DD')

                const dateTo = dateToDayjs ? dateToDayjs.format('YYYY-MM-DD') : dayjs().format('YYYY-MM-DD')

                const queryConfig = {
                    dateFrom,
                    dateTo,
                    requestNameBreakdownEnabled,
                    requestNameFilter,
                }

                const expensiveQueriesColumns = createExpensiveQueriesColumns(requestNameBreakdownEnabled)
                const last20QueriesColumns = createLast20QueriesColumns(requestNameBreakdownEnabled)
                const failedQueriesColumns = createFailedQueriesColumns()

                const apiQueriesCountQuery = createApiQueriesCountQuery(queryConfig)
                const apiReadTbQuery = createApiReadTbQuery(queryConfig)
                const apiCpuSecondsQuery = createApiCpuSecondsQuery(queryConfig)
                const apiQueriesPerKeyQuery = createApiQueriesPerKeyQuery(queryConfig)
                const last20QueriesQuery = createLast20QueriesQuery(queryConfig)
                const expensiveQueriesQuery = createExpensiveQueriesQuery(queryConfig)
                const failedQueriesQuery = createFailedQueriesQuery(queryConfig)

                return [
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_QUERIES_COUNT,
                        title: 'Number of API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiQueriesCountQuery,
                            },
                            display: ChartDisplayType.ActionsBar,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'number_of_queries',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_api_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_READ_TB,
                        title: 'TB read by API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiReadTbQuery,
                            },
                            display: ChartDisplayType.ActionsBar,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'read_tb',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_read_tb',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_CPU_SECONDS,
                        title: 'CPU seconds used by API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiCpuSecondsQuery,
                            },
                            display: ChartDisplayType.ActionsLineGraph,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'cpu_sec',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_cpu_sec',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_QUERIES_PER_KEY,
                        title: 'Number of API requests by personal api key per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiQueriesPerKeyQuery,
                            },
                            display: ChartDisplayType.ActionsLineGraph,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'total_queries',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: true,
                                seriesBreakdownColumn: 'api_key_label',
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_queries_per_key',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_LAST_20_QUERIES,
                        title: 'Last 20 API requests',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: last20QueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            tableSettings: {
                                columns: last20QueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_last_20_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_EXPENSIVE_QUERIES,
                        title: '25 most expensive API request queries',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: expensiveQueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            tableSettings: {
                                columns: expensiveQueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_expensive_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EndpointsUsageTileId.API_FAILED_QUERIES,
                        title: 'Recently failed API request queries',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: failedQueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            tableSettings: {
                                columns: failedQueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_failed_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                ]
            },
        ],

        breadcrumbs: [
            (s) => [s.activeTab],
            (): Breadcrumb[] => [
                {
                    key: 'Endpoints',
                    name: 'Endpoints',
                    iconType: 'endpoints',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRequestNames()
    }),

    tabAwareActionToUrl(({ values }) => {
        const actionToUrl = ({
            dateFilter = values.dateFilter,
            requestNameBreakdownEnabled = values.requestNameBreakdownEnabled,
            requestNameFilter = values.requestNameFilter,
        }): [string, Record<string, any> | undefined, string | undefined] | undefined => {
            const { dateFrom, dateTo } = dateFilter
            const searchParams = { ...router.values.searchParams }

            if (values.activeTab == 'usage') {
                if (dateFrom !== INITIAL_DATE_FROM) {
                    searchParams.dateFrom = dateFrom
                } else {
                    delete searchParams.dateFrom
                }

                if (dateTo !== INITIAL_DATE_TO) {
                    searchParams.dateTo = dateTo
                } else {
                    delete searchParams.dateTo
                }

                if (requestNameBreakdownEnabled !== INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED) {
                    searchParams.requestNameBreakdownEnabled = requestNameBreakdownEnabled
                } else {
                    delete searchParams.requestNameBreakdownEnabled
                }

                if (requestNameFilter.length > 0) {
                    searchParams.requestNameFilter = requestNameFilter.join(',')
                } else {
                    delete searchParams.requestNameFilter
                }
            } else {
                delete searchParams.dateFrom
                delete searchParams.dateTo
                delete searchParams.requestNameBreakdownEnabled
                delete searchParams.requestNameFilter
            }

            return [router.values.location.pathname, searchParams, router.values.location.hash]
        }

        return {
            setDates: actionToUrl,
            setRequestNameBreakdownEnabled: actionToUrl,
            setRequestNameFilter: actionToUrl,
        }
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.endpointsUsage()]: (_, searchParams) => {
            const { dateFrom, dateTo, requestNameBreakdownEnabled, requestNameFilter } = searchParams
            actions.setDates(dateFrom ?? INITIAL_DATE_FROM, dateTo ?? INITIAL_DATE_TO)
            actions.setRequestNameBreakdownEnabled(
                requestNameBreakdownEnabled ?? INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED
            )
            actions.setRequestNameFilter(requestNameFilter ? requestNameFilter.split(',') : [])
        },
    })),
])
