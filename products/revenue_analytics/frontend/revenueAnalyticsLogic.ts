import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { getDefaultInterval, objectsEqual } from 'lib/utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { isRevenueAnalyticsPropertyFilters } from '~/queries/schema-guards'
import {
    DataTableNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsPropertyFilters,
    RevenueAnalyticsTopCustomersGroupBy,
} from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps, InsightShortId, SimpleIntervalType } from '~/types'

import type { revenueAnalyticsLogicType } from './revenueAnalyticsLogicType'
import { revenueAnalyticsSettingsLogic } from './settings/revenueAnalyticsSettingsLogic'

export enum RevenueAnalyticsQuery {
    OVERVIEW,
    MRR,
    GROSS_REVENUE,
    METRICS,
    TOP_CUSTOMERS,
}

export const REVENUE_ANALYTICS_QUERY_TO_SHORT_ID: Record<RevenueAnalyticsQuery, InsightShortId> = {
    [RevenueAnalyticsQuery.OVERVIEW]: 'revenue-analytics-overview' as InsightShortId,
    [RevenueAnalyticsQuery.MRR]: 'revenue-analytics-mrr' as InsightShortId,
    [RevenueAnalyticsQuery.GROSS_REVENUE]: 'revenue-analytics-gross-revenue' as InsightShortId,
    [RevenueAnalyticsQuery.METRICS]: 'revenue-analytics-metrics' as InsightShortId,
    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: 'revenue-analytics-top-customers' as InsightShortId,
}

export const REVENUE_ANALYTICS_QUERY_TO_NAME: Record<RevenueAnalyticsQuery, string> = {
    [RevenueAnalyticsQuery.OVERVIEW]: 'Revenue Analytics Overview',
    [RevenueAnalyticsQuery.MRR]: 'MRR',
    [RevenueAnalyticsQuery.GROSS_REVENUE]: 'Gross Revenue',
    [RevenueAnalyticsQuery.METRICS]: 'Revenue Metrics',
    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: 'Top Customers',
}

export const REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID = 'revenue-analytics'

// Type needs to look like this to be able to apss this to
export const buildDashboardItemId = (queryType: RevenueAnalyticsQuery): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.revenue-analytics.${queryType}`
}

const getDefaultRevenueAnalyticsInterval = (dateFrom: string | null, dateTo: string | null): SimpleIntervalType => {
    const interval = getDefaultInterval(dateFrom, dateTo)
    return interval === 'day' ? 'day' : 'month'
}

const INITIAL_REVENUE_ANALYTICS_FILTER = [] as RevenueAnalyticsPropertyFilters
const INITIAL_DATE_FROM = 'yStart' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL: SimpleIntervalType = getDefaultRevenueAnalyticsInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)
const INITIAL_DATE_FILTER = {
    dateFrom: INITIAL_DATE_FROM,
    dateTo: INITIAL_DATE_TO,
    interval: INITIAL_INTERVAL,
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}_v2__` }

const wrapWithDataTableNodeIfNeeded = (
    query: DataTableNode['source'],
    columns: string[],
    isNeeded: boolean
): QuerySchema => {
    if (!isNeeded) {
        return query
    }

    return {
        kind: NodeKind.DataTableNode,
        source: query,
        full: true,
        embedded: false,
        showActions: true,
        columns,
    }
}

const setQueryParams = (params: Record<string, string>): string => {
    const searchParams = { ...router.values.searchParams }
    const urlParams = new URLSearchParams(searchParams)
    Object.entries(params).forEach(([key, value]) => {
        urlParams.set(key, value)
    })

    return `${urls.revenueAnalytics()}${urlParams.toString() ? '?' + urlParams.toString() : ''}`
}

export type MRRMode = 'mrr' | 'arr'
export type DisplayMode = 'line' | 'area' | 'bar' | 'table'

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['baseCurrency'],
            revenueAnalyticsSettingsLogic,
            ['events', 'dataWarehouseSources', 'goals as revenueGoals'],
        ],
        actions: [dataWarehouseSettingsLogic, ['loadSourcesSuccess']],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setRevenueAnalyticsFilters: (revenueAnalyticsFilters: RevenueAnalyticsPropertyFilters) => ({
            revenueAnalyticsFilters,
        }),
        setMRRMode: (mrrMode: MRRMode) => ({ mrrMode }),
        setInsightsDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        setTopCustomersDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        setBreakdownProperties: (breakdownProperties: RevenueAnalyticsBreakdown[]) => ({ breakdownProperties }),
        addBreakdown: (breakdown: RevenueAnalyticsBreakdown) => ({ breakdown }),
        removeBreakdown: (breakdown: RevenueAnalyticsBreakdown) => ({ breakdown }),
    }),
    reducers(() => ({
        dateFilter: [
            INITIAL_DATE_FILTER,
            persistConfig,
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultRevenueAnalyticsInterval(dateFrom, dateTo),
                }),
            },
        ],
        revenueAnalyticsFilter: [
            INITIAL_REVENUE_ANALYTICS_FILTER,
            persistConfig,
            { setRevenueAnalyticsFilters: (_, { revenueAnalyticsFilters }) => revenueAnalyticsFilters },
        ],
        breakdownProperties: [
            [] as RevenueAnalyticsBreakdown[],
            persistConfig,
            {
                addBreakdown: (state, { breakdown }) => {
                    if (state.length >= 2) {
                        return state
                    }

                    if (state.some((b) => b.property === breakdown.property && b.type === breakdown.type)) {
                        return state
                    }

                    return [...state, breakdown]
                },
                removeBreakdown: (state, { breakdown }) => {
                    return state.filter((b) => b.property !== breakdown.property || b.type !== breakdown.type)
                },
                setBreakdownProperties: (_, { breakdownProperties }) => breakdownProperties,
            },
        ],
        mrrMode: [
            'mrr' as MRRMode,
            persistConfig,
            {
                setMRRMode: (_, { mrrMode }) => mrrMode,
            },
        ],
        insightsDisplayMode: [
            'line' as DisplayMode,
            persistConfig,
            {
                setInsightsDisplayMode: (_, { displayMode }) => displayMode,
            },
        ],
        topCustomersDisplayMode: [
            'line' as DisplayMode,
            persistConfig,
            {
                setTopCustomersDisplayMode: (_, { displayMode }) => displayMode,
                setDates: (state, { dateTo, dateFrom }) => {
                    const interval = getDefaultRevenueAnalyticsInterval(dateFrom, dateTo)
                    if (interval !== 'month') {
                        return 'table'
                    }

                    return state
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'RevenueAnalytics',
                    name: 'Revenue analytics',
                    path: urls.revenueAnalytics(),
                    iconType: 'revenue_analytics',
                },
            ],
        ],

        revenueEnabledEvents: [(s) => [s.events], (events) => events],
        revenueEnabledDataWarehouseSources: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources) =>
                dataWarehouseSources === null
                    ? null
                    : dataWarehouseSources.results.filter((source) => source.revenue_analytics_config.enabled),
        ],

        disabledGrowthModeSelection: [(s) => [s.dateFilter], (dateFilter): boolean => dateFilter.interval !== 'month'],

        disabledTopCustomersModeSelection: [
            (s) => [s.dateFilter],
            (dateFilter): boolean => dateFilter.interval !== 'month',
        ],

        hasRevenueEvents: [
            (s) => [s.revenueEnabledEvents],
            (events): boolean => {
                return events.length > 0
            },
        ],

        hasRevenueTables: [
            (s) => [s.revenueEnabledDataWarehouseSources],
            (dataWarehouseSources): boolean | null => {
                // Indicate loading state with `null` if we haven't loaded this yet
                if (dataWarehouseSources === null) {
                    return null
                }

                return Boolean(dataWarehouseSources.length)
            },
        ],

        queries: [
            (s) => [s.dateFilter, s.revenueAnalyticsFilter, s.topCustomersDisplayMode, s.breakdownProperties],
            (
                dateFilter,
                revenueAnalyticsFilter,
                topCustomersDisplayMode,
                breakdown
            ): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const topCustomersGroupBy: RevenueAnalyticsTopCustomersGroupBy =
                    topCustomersDisplayMode === 'table' ? 'all' : 'month'

                return {
                    [RevenueAnalyticsQuery.OVERVIEW]: {
                        kind: NodeKind.RevenueAnalyticsOverviewQuery,
                        properties: revenueAnalyticsFilter,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.MRR]: {
                        kind: NodeKind.RevenueAnalyticsMRRQuery,
                        properties: revenueAnalyticsFilter,
                        breakdown,
                        interval,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.GROSS_REVENUE]: {
                        kind: NodeKind.RevenueAnalyticsGrossRevenueQuery,
                        properties: revenueAnalyticsFilter,
                        breakdown,
                        interval,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.METRICS]: {
                        kind: NodeKind.RevenueAnalyticsMetricsQuery,
                        properties: revenueAnalyticsFilter,
                        breakdown,
                        interval,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: wrapWithDataTableNodeIfNeeded(
                        {
                            kind: NodeKind.RevenueAnalyticsTopCustomersQuery,
                            properties: revenueAnalyticsFilter,
                            dateRange,
                            groupBy: topCustomersGroupBy,
                        },
                        ['name', 'customer_id', 'amount', 'month'],
                        topCustomersGroupBy === 'all'
                    ),
                }
            },
        ],

        maxContext: [
            (s) => [s.queries],
            (queries): MaxContextInput[] => {
                return [
                    createMaxContextHelpers.insight(
                        {
                            id: RevenueAnalyticsQuery.MRR,
                            short_id: REVENUE_ANALYTICS_QUERY_TO_SHORT_ID[RevenueAnalyticsQuery.MRR],
                            name: REVENUE_ANALYTICS_QUERY_TO_NAME[RevenueAnalyticsQuery.MRR],
                            query: queries[RevenueAnalyticsQuery.MRR],
                        },
                        {
                            revenueAnalyticsQuery: RevenueAnalyticsQuery.MRR,
                        }
                    ),
                    createMaxContextHelpers.insight(
                        {
                            id: RevenueAnalyticsQuery.GROSS_REVENUE,
                            short_id: REVENUE_ANALYTICS_QUERY_TO_SHORT_ID[RevenueAnalyticsQuery.GROSS_REVENUE],
                            name: REVENUE_ANALYTICS_QUERY_TO_NAME[RevenueAnalyticsQuery.GROSS_REVENUE],
                            query: queries[RevenueAnalyticsQuery.GROSS_REVENUE],
                        },
                        {
                            revenueAnalyticsQuery: RevenueAnalyticsQuery.GROSS_REVENUE,
                        }
                    ),
                    createMaxContextHelpers.insight(
                        {
                            id: RevenueAnalyticsQuery.METRICS,
                            short_id: REVENUE_ANALYTICS_QUERY_TO_SHORT_ID[RevenueAnalyticsQuery.METRICS],
                            name: REVENUE_ANALYTICS_QUERY_TO_NAME[RevenueAnalyticsQuery.METRICS],
                            query: queries[RevenueAnalyticsQuery.METRICS],
                        },
                        {
                            revenueAnalyticsQuery: RevenueAnalyticsQuery.METRICS,
                        }
                    ),
                    createMaxContextHelpers.insight(
                        {
                            id: RevenueAnalyticsQuery.TOP_CUSTOMERS,
                            short_id: REVENUE_ANALYTICS_QUERY_TO_SHORT_ID[RevenueAnalyticsQuery.TOP_CUSTOMERS],
                            name: REVENUE_ANALYTICS_QUERY_TO_NAME[RevenueAnalyticsQuery.TOP_CUSTOMERS],
                            query: queries[RevenueAnalyticsQuery.TOP_CUSTOMERS],
                        },
                        {
                            revenueAnalyticsQuery: RevenueAnalyticsQuery.TOP_CUSTOMERS,
                        }
                    ),
                ]
            },
        ],
    }),
    tabAwareActionToUrl(() => ({
        setDates: ({ dateFrom, dateTo }): string =>
            setQueryParams({ date_from: dateFrom ?? '', date_to: dateTo ?? '' }),
        setRevenueAnalyticsFilters: ({ revenueAnalyticsFilters }): string =>
            setQueryParams({ filters: JSON.stringify(revenueAnalyticsFilters) }),
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.revenueAnalytics()]: (_, { filters, date_from, date_to }) => {
            if (
                (date_from && date_from !== values.dateFilter.dateFrom) ||
                (date_to && date_to !== values.dateFilter.dateTo)
            ) {
                actions.setDates(date_from, date_to)
            }

            const parsedFilters = isRevenueAnalyticsPropertyFilters(filters) ? filters : undefined
            if (parsedFilters && !objectsEqual(parsedFilters, values.revenueAnalyticsFilter)) {
                actions.setRevenueAnalyticsFilters(parsedFilters)
            }
        },
    })),
])
