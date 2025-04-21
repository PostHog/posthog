import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { getDefaultInterval } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSceneLogic'
import { urls } from 'scenes/urls'

import {
    DataTableNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsTopCustomersGroupBy,
} from '~/queries/schema/schema-general'
import { Breadcrumb, ChartDisplayType, InsightLogicProps, PropertyMathType } from '~/types'

import type { revenueAnalyticsLogicType } from './revenueAnalyticsLogicType'
import { revenueEventsSettingsLogic } from './settings/revenueEventsSettingsLogic'

// Keep in sync with `revenue_analytics/backend/models.py`
const CHARGE_REVENUE_VIEW_SUFFIX = 'charge_revenue_view'

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

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    connect(() => ({
        values: [
            dataWarehouseSceneLogic,
            ['dataWarehouseTablesBySourceType'],
            databaseTableListLogic,
            ['database', 'managedViews'],
            revenueEventsSettingsLogic,
            ['baseCurrency'],
        ],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setTopCustomersDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
        setGrowthRateDisplayMode: (displayMode: LineOrTableChart) => ({ displayMode }),
    }),
    reducers({
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
    }),
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

        disabledGrowthModeSelection: [(s) => [s.dateFilter], (dateFilter): boolean => dateFilter.interval !== 'month'],

        disabledTopCustomersModeSelection: [
            (s) => [s.dateFilter],
            (dateFilter): boolean => dateFilter.interval !== 'month',
        ],

        hasRevenueTables: [
            (s) => [s.database, s.dataWarehouseTablesBySourceType],
            (database, dataWarehouseTablesBySourceType): boolean | null => {
                // Indicate loading state with `null` if we don't have a database yet
                if (database === null) {
                    return null
                }

                // Eventually we'll want to look at our revenue views,
                // but for now checking whether we have Stripe tables is enough
                return Boolean(dataWarehouseTablesBySourceType['Stripe']?.length)
            },
        ],

        queries: [
            (s) => [s.dateFilter, s.managedViews, s.topCustomersDisplayMode, s.growthRateDisplayMode, s.baseCurrency],
            (
                dateFilter,
                managedViews,
                topCustomersDisplayMode,
                growthRateDisplayMode,
                baseCurrency
            ): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const chargeViews = managedViews.filter((view) => view.name.includes(CHARGE_REVENUE_VIEW_SUFFIX))

                const topCustomersGroupBy: RevenueAnalyticsTopCustomersGroupBy =
                    topCustomersDisplayMode === 'table' ? 'all' : 'month'

                const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

                return {
                    [RevenueAnalyticsQuery.OVERVIEW]: {
                        kind: NodeKind.RevenueAnalyticsOverviewQuery,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.GROSS_REVENUE]: {
                        kind: NodeKind.InsightVizNode,
                        embedded: false,
                        hidePersonsModal: true,
                        hideTooltipOnScroll: true,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: chargeViews.map((view) => ({
                                kind: NodeKind.DataWarehouseNode,
                                id: view.name,
                                name: view.name,
                                custom_name:
                                    chargeViews.length > 1 ? `Gross revenue for ${view.name}` : 'Gross revenue',
                                id_field: 'id',
                                timestamp_field: 'timestamp',
                                distinct_id_field: 'id',
                                table_name: view.name,
                                math: PropertyMathType.Sum,
                                math_property: 'amount',
                            })),
                            interval,
                            dateRange,
                            trendsFilter: {
                                display:
                                    chargeViews.length > 1
                                        ? ChartDisplayType.ActionsAreaGraph
                                        : ChartDisplayType.ActionsLineGraph,
                                aggregationAxisFormat: 'numeric',
                                aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                                aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                            },
                        },
                    },
                    [RevenueAnalyticsQuery.REVENUE_GROWTH_RATE]: wrapWithDataTableNodeIfNeeded(
                        { kind: NodeKind.RevenueAnalyticsGrowthRateQuery, dateRange },
                        ['month', 'mrr', 'previous_mrr', 'mrr_growth_rate'],
                        growthRateDisplayMode === 'table'
                    ),
                    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: wrapWithDataTableNodeIfNeeded(
                        {
                            kind: NodeKind.RevenueAnalyticsTopCustomersQuery,
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
])
