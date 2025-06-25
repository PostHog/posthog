import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { getDefaultInterval, objectsEqual } from 'lib/utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    DataTableNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsInsightsQueryGroupBy,
    RevenueAnalyticsPropertyFilters,
    RevenueAnalyticsTopCustomersGroupBy,
} from '~/queries/schema/schema-general'
import { isRevenueAnalyticsPropertyFilters } from '~/queries/schema-guards'
import { Breadcrumb, InsightLogicProps } from '~/types'

import type { revenueAnalyticsLogicType } from './revenueAnalyticsLogicType'
import { revenueAnalyticsSettingsLogic } from './settings/revenueAnalyticsSettingsLogic'

export enum RevenueAnalyticsQuery {
    OVERVIEW,
    GROSS_REVENUE,
    REVENUE_GROWTH_RATE,
    TOP_CUSTOMERS,
}

export const REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID = 'revenue-analytics'

// Type needs to look like this to be able to apss this to
export const buildDashboardItemId = (queryType: RevenueAnalyticsQuery): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.revenue-analytics.${queryType}`
}

const INITIAL_REVENUE_ANALYTICS_FILTER = [] as RevenueAnalyticsPropertyFilters
const INITIAL_DATE_FROM = 'yStart' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)
const INITIAL_DATE_FILTER = {
    dateFrom: INITIAL_DATE_FROM,
    dateTo: INITIAL_DATE_TO,
    interval: INITIAL_INTERVAL,
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

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
        setInsightsDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        setTopCustomersDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        setGrowthRateDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        setGroupBy: (groupBy: RevenueAnalyticsInsightsQueryGroupBy[]) => ({ groupBy }),
    }),
    reducers(() => ({
        dateFilter: [
            INITIAL_DATE_FILTER,
            persistConfig,
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultInterval(dateFrom, dateTo),
                }),
            },
        ],
        revenueAnalyticsFilter: [
            INITIAL_REVENUE_ANALYTICS_FILTER,
            persistConfig,
            { setRevenueAnalyticsFilters: (_, { revenueAnalyticsFilters }) => revenueAnalyticsFilters },
        ],
        groupBy: [
            [] as RevenueAnalyticsInsightsQueryGroupBy[],
            persistConfig,
            {
                setGroupBy: (_, { groupBy }) => groupBy,
            },
        ],
        insightsDisplayMode: [
            'line' as DisplayMode,
            persistConfig,
            {
                setInsightsDisplayMode: (_, { displayMode }) => displayMode,
            },
        ],
        growthRateDisplayMode: [
            'line' as DisplayMode,
            persistConfig,
            {
                setGrowthRateDisplayMode: (_, { displayMode }) => displayMode,
                setDates: (state, { dateTo, dateFrom }) => {
                    const interval = getDefaultInterval(dateFrom, dateTo)
                    if (interval !== 'month') {
                        return 'table'
                    }

                    return state
                },
            },
        ],
        topCustomersDisplayMode: [
            'line' as DisplayMode,
            persistConfig,
            {
                setTopCustomersDisplayMode: (_, { displayMode }) => displayMode,
                setDates: (state, { dateTo, dateFrom }) => {
                    const interval = getDefaultInterval(dateFrom, dateTo)
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
                },
            ],
        ],

        revenueEnabledEvents: [(s) => [s.events], (events) => events],
        revenueEnabledDataWarehouseSources: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources) =>
                dataWarehouseSources === null
                    ? null
                    : dataWarehouseSources.results.filter((source) => source.revenue_analytics_enabled),
        ],

        disabledGrowthModeSelection: [(s) => [s.dateFilter], (dateFilter): boolean => dateFilter.interval !== 'month'],

        disabledTopCustomersModeSelection: [
            (s) => [s.dateFilter],
            (dateFilter): boolean => dateFilter.interval !== 'month',
        ],

        hasRevenueEvents: [(s) => [s.revenueEnabledEvents], (events): boolean => events.length > 0],

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
            (s) => [
                s.dateFilter,
                s.revenueAnalyticsFilter,
                s.topCustomersDisplayMode,
                s.growthRateDisplayMode,
                s.groupBy,
            ],
            (
                dateFilter,
                revenueAnalyticsFilter,
                topCustomersDisplayMode,
                growthRateDisplayMode,
                groupBy
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
                    [RevenueAnalyticsQuery.GROSS_REVENUE]: {
                        kind: NodeKind.RevenueAnalyticsInsightsQuery,
                        properties: revenueAnalyticsFilter,
                        groupBy,
                        interval,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.REVENUE_GROWTH_RATE]: wrapWithDataTableNodeIfNeeded(
                        {
                            kind: NodeKind.RevenueAnalyticsGrowthRateQuery,
                            properties: revenueAnalyticsFilter,
                            dateRange,
                        },
                        ['month', 'mrr', 'previous_mrr', 'mrr_growth_rate'],
                        growthRateDisplayMode === 'table'
                    ),
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
    }),
    actionToUrl(() => ({
        setDates: ({ dateFrom, dateTo }): string =>
            setQueryParams({ date_from: dateFrom ?? '', date_to: dateTo ?? '' }),
        setRevenueAnalyticsFilters: ({ revenueAnalyticsFilters }): string =>
            setQueryParams({ filters: JSON.stringify(revenueAnalyticsFilters) }),
    })),
    urlToAction(({ actions, values }) => ({
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
