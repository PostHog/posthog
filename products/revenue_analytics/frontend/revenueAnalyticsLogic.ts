import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { getDefaultInterval } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { maxContextLogic } from '~/lib/ai/maxContextLogic'
import {
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaManagedViewTableKind,
    DataTableNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsEventItem,
    RevenueAnalyticsTopCustomersGroupBy,
} from '~/queries/schema/schema-general'
import { Breadcrumb, ChartDisplayType, ExternalDataSource, InsightLogicProps, PropertyMathType } from '~/types'

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
        actions: [
            dataWarehouseSettingsLogic,
            ['loadSourcesSuccess'],
            maxContextLogic,
            ['addRevenueAnalyticsQueries', 'clearRevenueAnalyticsQueries'],
        ],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setTopCustomersDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
        setGrowthRateDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
        setRevenueSources: (revenueSources: RawRevenueSources) => ({ revenueSources }),
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
            (s) => [
                s.dateFilter,
                s.rawRevenueSources,
                s.chargeRevenueViews,
                s.revenueGoals,
                s.topCustomersDisplayMode,
                s.growthRateDisplayMode,
                s.baseCurrency,
            ],
            (
                dateFilter,
                rawRevenueSources,
                chargeRevenueViews,
                revenueGoals,
                topCustomersDisplayMode,
                growthRateDisplayMode,
                baseCurrency
            ): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const topCustomersGroupBy: RevenueAnalyticsTopCustomersGroupBy =
                    topCustomersDisplayMode === 'table' ? 'all' : 'month'

                const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

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
                        kind: NodeKind.InsightVizNode,
                        embedded: false,
                        hidePersonsModal: true,
                        hideTooltipOnScroll: true,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: chargeRevenueViews.map((view) => ({
                                kind: NodeKind.DataWarehouseNode,
                                id: view.name,
                                name: view.name,
                                custom_name:
                                    chargeRevenueViews.length > 1 ? `Gross revenue for ${view.name}` : 'Gross revenue',
                                id_field: 'id',
                                distinct_id_field: 'id',
                                timestamp_field: 'timestamp',
                                table_name: view.name,
                                math: PropertyMathType.Sum,
                                math_property: 'amount',
                            })),
                            interval,
                            dateRange,
                            trendsFilter: {
                                display:
                                    chargeRevenueViews.length > 1
                                        ? ChartDisplayType.ActionsAreaGraph
                                        : ChartDisplayType.ActionsLineGraph,
                                aggregationAxisFormat: 'numeric',
                                aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                                aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                                goalLines: revenueGoals.map((goal) => {
                                    const isFuture = dayjs(goal.due_date).isSameOrAfter(dayjs())

                                    return {
                                        label: `${goal.name} (${dayjs(goal.due_date).format('DD MMM YYYY')})`,
                                        value: goal.goal,
                                        displayLabel: true,
                                        borderColor: isFuture ? 'green' : 'red',

                                        // Only display smaller goals that are in the future
                                        // This implies that past goals that have been achieved already
                                        // will not be displayed
                                        displayIfCrossed: isFuture,
                                    }
                                }),
                            },
                        },
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
        setDates: ({ dateFrom, dateTo }): string => {
            const searchParams = { ...router.values.searchParams }
            const urlParams = new URLSearchParams(searchParams)

            urlParams.set('date_from', dateFrom ?? '')
            urlParams.set('date_to', dateTo ?? '')

            return `${urls.revenueAnalytics()}${urlParams.toString() ? '?' + urlParams.toString() : ''}`
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.revenueAnalytics()]: (_, { date_from, date_to }) => {
            if (
                (date_from && date_from !== values.dateFilter.dateFrom) ||
                (date_to && date_to !== values.dateFilter.dateTo)
            ) {
                actions.setDates(date_from, date_to)
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
        setDates: () => {
            actions.addRevenueAnalyticsQueries(values.queries)
        },
        setRevenueSources: () => {
            actions.addRevenueAnalyticsQueries(values.queries)
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

        // Add queries to max context on mount
        if (values.queries) {
            actions.addRevenueAnalyticsQueries(values.queries)
        }
    }),
])
