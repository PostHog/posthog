import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { urls } from 'scenes/urls'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    HogQLMathType,
    InsightShortId,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsDashboardLogicType } from './llmAnalyticsDashboardLogicType'

export interface QueryTile {
    title: string
    description?: string
    query: TrendsQuery
    context?: QueryContext
    layout?: {
        className?: string
    }
}

/**
 * Helper function to get date range for a specific day.
 * @param day - The day string from the chart (e.g., "2024-01-15")
 * @returns Object with date_from and date_to formatted strings
 */
function getDayDateRange(day: string): { date_from: string; date_to: string } {
    const dayStart = dayjs(day).startOf('day')

    return {
        date_from: dayStart.format('YYYY-MM-DD[T]HH:mm:ss'),
        date_to: dayStart.add(1, 'day').subtract(1, 'second').format('YYYY-MM-DD[T]HH:mm:ss'),
    }
}

export const llmAnalyticsDashboardLogic = kea<llmAnalyticsDashboardLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsDashboardLogic']),
    connect({
        values: [llmAnalyticsSharedLogic, ['dashboardDateFilter', 'shouldFilterTestAccounts', 'propertyFilters']],
    }),

    actions({
        refreshAllDashboardItems: true,
        setRefreshStatus: (tileId: string, loading?: boolean) => ({ tileId, loading }),
        loadLLMDashboards: true,
    }),

    reducers({
        refreshStatus: [
            {} as Record<string, { loading?: boolean; timer?: Date }>,
            {
                setRefreshStatus: (state, { tileId, loading }) => ({
                    ...state,
                    [tileId]: loading ? { loading: true, timer: new Date() } : state[tileId],
                }),
                refreshAllDashboardItems: () => ({}),
            },
        ],

        newestRefreshed: [
            null as Date | null,
            {
                setRefreshStatus: (state, { loading }) => (!loading ? new Date() : state),
            },
        ],

        selectedDashboardId: [
            null as number | null,
            { persist: true, prefix: 'llma_' },
            {
                loadLLMDashboardsSuccess: (state, { availableDashboards }) => {
                    // If no dashboards available, clear selection
                    if (availableDashboards.length === 0) {
                        return null
                    }

                    // If currently selected dashboard still exists in list, keep it
                    if (state && availableDashboards.some((d) => d.id === state)) {
                        return state
                    }

                    // Otherwise, select first available dashboard (new or after deletion)
                    return availableDashboards[0].id
                },
            },
        ],
    }),

    loaders(() => ({
        availableDashboards: [
            [] as Array<{ id: number; name: string; description: string }>,
            {
                loadLLMDashboards: async () => {
                    const response = await api.dashboards.list({
                        tags: 'llm-analytics',
                        creation_mode: 'unlisted',
                    })
                    const dashboards = response.results || []

                    return dashboards.map((d) => ({
                        id: d.id,
                        name: d.name,
                        description: d.description || '',
                    }))
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        loadLLMDashboardsSuccess: async ({ availableDashboards }, breakpoint) => {
            if (availableDashboards.length === 0) {
                try {
                    await api.dashboards.createUnlistedDashboard('llm-analytics')
                    await breakpoint(100)
                    actions.loadLLMDashboards()
                } catch (error: unknown) {
                    const err = error as { status?: number }

                    if (err.status === 409) {
                        await breakpoint(100)
                        actions.loadLLMDashboards()
                    } else {
                        console.error('Failed to create default LLM Analytics dashboard:', error)
                    }
                }
            }
        },

        refreshAllDashboardItems: async () => {
            // Set loading state for all tiles
            values.tiles.forEach((_, index) => {
                actions.setRefreshStatus(`tile-${index}`, true)
            })

            try {
                // Refresh all tiles in parallel
                values.tiles.map((tile, index) => {
                    const insightProps = {
                        dashboardItemId: tile.context?.insightProps?.dashboardItemId as InsightShortId,
                    }
                    const mountedInsightDataLogic = insightDataLogic.findMounted(insightProps)

                    if (mountedInsightDataLogic) {
                        mountedInsightDataLogic.actions.loadData('force_blocking')
                    }

                    actions.setRefreshStatus(`tile-${index}`, false)
                })
            } catch (error) {
                console.error('Error refreshing dashboard items:', error)
                // Clear loading states on error
                values.tiles.forEach((_, index) => {
                    actions.setRefreshStatus(`tile-${index}`, false)
                })
            }
        },
    })),

    selectors({
        isRefreshing: [
            (s) => [s.refreshStatus],
            (refreshStatus: Record<string, { loading?: boolean; timer?: Date }>) =>
                Object.values(refreshStatus).some((status) => status.loading),
        ],

        // IMPORTANT: Keep these hardcoded tiles in sync with backend template in
        // products/llm_analytics/backend/dashboard_templates.py:4-319 until full migration to customizable dashboard.
        //
        // Used when LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD feature flag is OFF.
        // When feature flag is ON, dashboard is loaded from backend template instead.
        tiles: [
            (s) => [s.dashboardDateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (dashboardDateFilter, shouldFilterTestAccounts, propertyFilters): QueryTile[] => [
                {
                    title: 'Traces',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: HogQLMathType.HogQL,
                                math_hogql: 'COUNT(DISTINCT properties.$ai_trace_id)',
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-traces-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                // NOTE: This assumes the chart is day-by-day
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsTraces(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generative AI users',
                    description: 'To count users, set `distinct_id` in LLM tracking.',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: (propertyFilters as AnyPropertyFilter[]).concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-generations-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)

                                router.actions.push(urls.llmAnalyticsUsers(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Cost',
                    description: 'Total cost of all generations',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 4,
                            display: ChartDisplayType.BoldNumber,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'traces',
                        onDataPointClick: () => {
                            router.actions.push(urls.llmAnalyticsTraces(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                            })
                        },
                    },
                },
                {
                    title: 'Cost per user',
                    description: "Average cost for each generative AI user active in the data point's period.",
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        trendsFilter: {
                            formula: 'A / B',
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: (propertyFilters as AnyPropertyFilter[]).concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-cost-per-user-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)

                                router.actions.push(urls.llmAnalyticsUsers(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Cost by model',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        breakdownFilter: {
                            breakdown_type: 'event',
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                            display: ChartDisplayType.ActionsBarValue,
                            showValuesOnSeries: true,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'traces',
                        onDataPointClick: ({ breakdown }) => {
                            router.actions.push(urls.llmAnalyticsTraces(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                                filters: [
                                    ...((router.values.searchParams.filters as AnyPropertyFilter[]) || []),
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$ai_model',
                                        operator: PropertyOperator.Exact,
                                        value: breakdown as string,
                                    },
                                ],
                            })
                        },
                    },
                },
                {
                    title: 'Generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        insightProps: {
                            dashboardItemId: `new-generation-calls-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'AI Errors',
                    description: 'Failed AI generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: (propertyFilters as AnyPropertyFilter[]).concat({
                            type: PropertyFilterType.Event,
                            key: '$ai_is_error',
                            operator: PropertyOperator.Exact,
                            value: 'true',
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'errors',
                        insightProps: {
                            dashboardItemId: `new-ai-errors-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                    filters: [
                                        ...((router.values.searchParams.filters as AnyPropertyFilter[]) || []),
                                        {
                                            type: PropertyFilterType.Event,
                                            key: '$ai_is_error',
                                            operator: PropertyOperator.Exact,
                                            value: 'true',
                                        },
                                    ] as AnyPropertyFilter[],
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generation latency by model (median)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Median,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_latency',
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPostfix: ' s',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        insightProps: {
                            dashboardItemId: `new-generation-latency-by-model-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                    filters: [
                                        ...((router.values.searchParams.filters as AnyPropertyFilter[]) || []),
                                        {
                                            type: PropertyFilterType.Event,
                                            key: '$ai_model',
                                            operator: PropertyOperator.Exact,
                                            value: series.breakdown as string,
                                        },
                                    ] as AnyPropertyFilter[],
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generations by HTTP status',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_http_status',
                        },
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBarValue,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        onDataPointClick: (series) => {
                            router.actions.push(urls.llmAnalyticsGenerations(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                                filters: [
                                    ...((router.values.searchParams.filters as AnyPropertyFilter[]) || []),
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$ai_http_status',
                                        operator: PropertyOperator.Exact,
                                        value: series.breakdown as string,
                                    },
                                ] as AnyPropertyFilter[],
                            })
                        },
                    },
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadLLMDashboards()
    }),
])
