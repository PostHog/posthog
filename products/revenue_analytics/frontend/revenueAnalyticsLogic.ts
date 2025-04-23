import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { getDefaultInterval } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSceneLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import {
    DataTableNode,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
    QuerySchema,
    RevenueAnalyticsTopCustomersGroupBy,
    RevenueTrackingEventItem,
} from '~/queries/schema/schema-general'
import { Breadcrumb, ChartDisplayType, ExternalDataSource, InsightLogicProps, PropertyMathType } from '~/types'

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
export type RawRevenueSources = {
    events: RevenueTrackingEventItem[]
    dataWarehouseSources: ExternalDataSource[]
}

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    connect(() => ({
        values: [
            dataWarehouseSceneLogic,
            ['dataWarehouseTablesBySourceType'],
            databaseTableListLogic,
            ['database'],
            revenueEventsSettingsLogic,
            ['baseCurrency', 'events as allEvents', 'dataWarehouseSources as allDataWarehouseSources'],
        ],
        actions: [dataWarehouseSettingsLogic, ['loadSourcesSuccess']],
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

        disabledGrowthModeSelection: [(s) => [s.dateFilter], (dateFilter): boolean => dateFilter.interval !== 'month'],

        disabledTopCustomersModeSelection: [
            (s) => [s.dateFilter],
            (dateFilter): boolean => dateFilter.interval !== 'month',
        ],

        // TODO: Update how we detect whether we have revenue tables or not
        // There are more cases because we might have revenue sources,
        // but they might be simply disabled
        // We should probably wait until `loadSourcesSuccess` is properly called
        // to guarantee we include all revenue tables
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
            (s) => [
                s.dateFilter,
                s.rawRevenueSources,
                s.topCustomersDisplayMode,
                s.growthRateDisplayMode,
                s.baseCurrency,
            ],
            (
                dateFilter,
                rawRevenueSources,
                topCustomersDisplayMode,
                growthRateDisplayMode,
                baseCurrency
            ): Record<RevenueAnalyticsQuery, QuerySchema> => {
                const { dateFrom, dateTo, interval } = dateFilter
                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const topCustomersGroupBy: RevenueAnalyticsTopCustomersGroupBy =
                    topCustomersDisplayMode === 'table' ? 'all' : 'month'

                const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

                const chargeViews = rawRevenueSources.dataWarehouseSources.map((source) => {
                    return source.prefix
                        ? `${source.source_type.toLocaleLowerCase()}.${source.prefix}.${CHARGE_REVENUE_VIEW_SUFFIX}`
                        : `${source.source_type.toLocaleLowerCase()}.${CHARGE_REVENUE_VIEW_SUFFIX}`
                })

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
                            series: [
                                ...chargeViews.map((view) => ({
                                    kind: NodeKind.DataWarehouseNode,
                                    id: view,
                                    name: view,
                                    custom_name: chargeViews.length > 1 ? `Gross revenue for ${view}` : 'Gross revenue',
                                    id_field: 'id',
                                    timestamp_field: 'timestamp',
                                    distinct_id_field: 'id',
                                    table_name: view,
                                    math: PropertyMathType.Sum,
                                    math_property: 'amount',
                                })),
                                ...rawRevenueSources.events.map((e) => ({
                                    name: e.eventName,
                                    event: e.eventName,
                                    custom_name: e.eventName,
                                    math: PropertyMathType.Sum,
                                    kind: NodeKind.EventsNode,
                                    math_property: e.revenueProperty,
                                    math_property_revenue_currency: e.revenueCurrencyProperty,
                                })),
                            ] as (EventsNode | DataWarehouseNode)[],
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
    listeners(({ actions, values }) => ({
        loadSourcesSuccess: ({ dataWarehouseSources }) => {
            actions.setRevenueSources({
                events: values.allEvents,
                dataWarehouseSources: dataWarehouseSources.results,
            })
        },
    })),
])
