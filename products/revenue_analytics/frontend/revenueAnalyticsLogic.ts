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

export enum RevenueAnalyticsQuery {
    OVERVIEW,
    GROSS_REVENUE,
    REVENUE_GROWTH_RATE,
    REVENUE_CHURN,
}

export const REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID = 'revenue-analytics'

// Type needs to look like this to be able to apss this to
export const buildDashboardItemId = (queryType: RevenueAnalyticsQuery): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.revenue-analytics.${queryType}`
}

const INITIAL_DATE_FROM = '-30d' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

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
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
    }),
    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            },
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
                setDatesAndInterval: (_, { dateTo, dateFrom, interval }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = INITIAL_DATE_FROM
                        dateTo = INITIAL_DATE_TO
                    }
                    return {
                        dateTo,
                        dateFrom,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
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
                            series: managedViews.map((view) => ({
                                kind: NodeKind.DataWarehouseNode,
                                id: view.name,
                                name: view.name,
                                custom_name:
                                    managedViews.length > 1 ? `Gross revenue for ${view.name}` : 'Gross revenue',
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
                                    managedViews.length > 1
                                        ? ChartDisplayType.ActionsAreaGraph
                                        : ChartDisplayType.ActionsLineGraph,
                                aggregationAxisFormat: 'numeric',
                                aggregationAxisPrefix: getCurrencySymbol(baseCurrency).symbol,
                            },
                        },
                    },
                    [RevenueAnalyticsQuery.REVENUE_GROWTH_RATE]: {
                        kind: NodeKind.RevenueAnalyticsGrowthRateQuery,
                        dateRange,
                    },
                    [RevenueAnalyticsQuery.REVENUE_CHURN]: {
                        kind: NodeKind.RevenueAnalyticsChurnRateQuery,
                        dateRange,
                    },
                }
            },
        ],
    }),
])
