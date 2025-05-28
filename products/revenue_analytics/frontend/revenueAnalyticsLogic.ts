import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { getDefaultInterval } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import {
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaManagedViewTableKind,
    DataTableNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsEventItem,
    RevenueAnalyticsTopCustomersGroupBy,
} from '~/queries/schema/schema-general'
import { Breadcrumb, ExternalDataSource, InsightLogicProps } from '~/types'

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

export type GrossRevenueGroupBy = 'all' | 'product' | 'cohort'
export type LineOrTableChart = 'line' | 'table'
export type RawRevenueSources = {
    events: RevenueAnalyticsEventItem[]
    dataWarehouseSources: ExternalDataSource[]
}

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['managedViews'],
            revenueAnalyticsSettingsLogic,
            ['baseCurrency', 'events', 'dataWarehouseSources', 'goals as revenueGoals'],
        ],
        actions: [dataWarehouseSettingsLogic, ['loadSourcesSuccess']],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setTopCustomersDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
        setGrowthRateDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
        setRevenueSources: (revenueSources: RawRevenueSources) => ({ revenueSources }),
        setGrossRevenueGroupBy: (groupBy: GrossRevenueGroupBy) => ({ groupBy }),
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

        grossRevenueGroupBy: [
            'all' as GrossRevenueGroupBy,
            persistConfig,
            {
                setGrossRevenueGroupBy: (_, { groupBy }) => groupBy,
            },
        ],
        growthRateDisplayMode: [
            'line' as LineOrTableChart,
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
            'line' as LineOrTableChart,
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

        rawRevenueSources: [
            {
                events: [],
                dataWarehouseSources: [],
            } as RawRevenueSources,
            {
                setRevenueSources: (_, { revenueSources }) => revenueSources,
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

        chargeRevenueViews: [
            (s) => [s.managedViews, s.rawRevenueSources],
            (managedViews, rawRevenueSources): DatabaseSchemaManagedViewTable[] => {
                if (!managedViews) {
                    return []
                }

                const dataWarehouseSourceIds = rawRevenueSources.dataWarehouseSources.map((source) => source.id)
                const eventNames = rawRevenueSources.events.map((e) => e.eventName.replace(/[^a-zA-Z0-9]/g, '_')) // Sanitizing event names to ensure they're valid as database identifiers - matches transformation in backend/views.py

                return managedViews
                    .filter((view) => view.kind === DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE)
                    .filter((view) => {
                        // Comes from a Data Warehouse source
                        if (view.source_id) {
                            return dataWarehouseSourceIds.includes(view.source_id)
                        }

                        // Comes from events
                        return eventNames.some((eventName) => view.name.includes(eventName))
                    })
            },
        ],

        queries: [
            (s) => [s.dateFilter, s.rawRevenueSources, s.topCustomersDisplayMode, s.growthRateDisplayMode],
            (
                dateFilter,
                rawRevenueSources,
                topCustomersDisplayMode,
                growthRateDisplayMode
            ): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const topCustomersGroupBy: RevenueAnalyticsTopCustomersGroupBy =
                    topCustomersDisplayMode === 'table' ? 'all' : 'month'

                // Convert from the raw revenue sources (events and data warehouse sources) to the revenue sources
                // that the RevenueAnalyticsOverviewQuery expects which is just a list of event names and data warehouse source IDs
                const revenueSources = {
                    events: rawRevenueSources.events.map((e) => e.eventName),
                    dataWarehouseSources: rawRevenueSources.dataWarehouseSources.map((s) => s.id),
                }

                return {
                    [RevenueAnalyticsQuery.OVERVIEW]: {
                        kind: NodeKind.RevenueAnalyticsOverviewQuery,
                        revenueSources,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.GROSS_REVENUE]: {
                        kind: NodeKind.RevenueAnalyticsInsightsQuery,
                        interval,
                        revenueSources,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.REVENUE_GROWTH_RATE]: wrapWithDataTableNodeIfNeeded(
                        { kind: NodeKind.RevenueAnalyticsGrowthRateQuery, dateRange, revenueSources },
                        ['month', 'mrr', 'previous_mrr', 'mrr_growth_rate'],
                        growthRateDisplayMode === 'table'
                    ),
                    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: wrapWithDataTableNodeIfNeeded(
                        {
                            kind: NodeKind.RevenueAnalyticsTopCustomersQuery,
                            dateRange,
                            revenueSources,
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
        setGrossRevenueGroupBy: ({ groupBy }): string => setQueryParams({ revenue_group_by: groupBy ?? '' }),
    })),
    urlToAction(({ actions, values }) => ({
        [urls.revenueAnalytics()]: (_, { date_from, date_to, revenue_group_by }) => {
            if (
                (date_from && date_from !== values.dateFilter.dateFrom) ||
                (date_to && date_to !== values.dateFilter.dateTo)
            ) {
                actions.setDates(date_from, date_to)
            }

            if (revenue_group_by && revenue_group_by !== values.grossRevenueGroupBy) {
                actions.setGrossRevenueGroupBy(revenue_group_by)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        loadSourcesSuccess: ({ dataWarehouseSources }) => {
            actions.setRevenueSources({
                events: values.events,
                dataWarehouseSources: dataWarehouseSources.results.filter((source) => source.revenue_analytics_enabled),
            })
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.events !== null && values.dataWarehouseSources !== null) {
            actions.setRevenueSources({
                events: values.events,
                dataWarehouseSources: values.dataWarehouseSources.results.filter(
                    (source) => source.revenue_analytics_enabled
                ),
            })
        }
    }),
])
