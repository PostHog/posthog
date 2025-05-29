import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { getDefaultInterval, updateDatesWithInterval } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSceneLogic'
import { urls } from 'scenes/urls'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { Breadcrumb, ChartDisplayType, InsightLogicProps, IntervalType, PropertyMathType } from '~/types'

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

const INITIAL_DATE_FROM = '-30d' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)
const INITIAL_DATE_FILTER = {
    dateFrom: INITIAL_DATE_FROM,
    dateTo: INITIAL_DATE_TO,
    interval: INITIAL_INTERVAL,
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    connect(() => ({
        values: [
            dataWarehouseSceneLogic,
            ['dataWarehouseTablesBySourceType'],
            databaseTableListLogic,
            ['managedViews'],
            revenueEventsSettingsLogic,
            ['baseCurrency'],
        ],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        resetDatesAndInterval: true,
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
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom,
                        interval,
                    }
                },
                resetDatesAndInterval: () => {
                    return INITIAL_DATE_FILTER
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

        hasRevenueTables: [
            (s) => [s.dataWarehouseTablesBySourceType],
            (dataWarehouseTablesBySourceType): boolean => Boolean(dataWarehouseTablesBySourceType['Stripe']?.length),
        ],

        queries: [
            (s) => [s.dateFilter, s.managedViews, s.baseCurrency],
            (dateFilter, managedViews, baseCurrency): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const chargeViews = managedViews.filter((view) => view.name.includes(CHARGE_REVENUE_VIEW_SUFFIX))

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
                                aggregationAxisPrefix: getCurrencySymbol(baseCurrency).symbol,
                            },
                        },
                    },
                    [RevenueAnalyticsQuery.REVENUE_GROWTH_RATE]: {
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.RevenueAnalyticsGrowthRateQuery,
                            dateRange,
                        },
                        full: true,
                        embedded: false,
                        showActions: true,
                        columns: ['month', 'mrr', 'previous_mrr', 'mrr_growth_rate'],
                    },
                    [RevenueAnalyticsQuery.TOP_CUSTOMERS]: {
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.RevenueAnalyticsTopCustomersQuery,
                            dateRange,
                        },
                        full: true,
                        embedded: false,
                        showActions: true,
                        columns: ['name', 'customer_id', 'amount', 'month'],
                    },
                }
            },
        ],
    }),
])
