import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import {
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
    marketingAnalyticsLogicValues,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import {
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { SearchMetrics, selectedSearchSources, searchPerformanceSource } from './searchPerformance'

export interface searchPerformanceLogicValues extends Pick<
    marketingAnalyticsLogicValues,
    'dataWarehouseSources' | 'dataWarehouseSourcesLoading' | 'dateFilter' | 'compareFilter' | 'integrationFilter'
> {
    metrics: SearchMetrics
    search: string
    querySearch: string
    sourcesError: boolean
    sources: ExternalDataSource[]
    pendingSources: ExternalDataSource[]
    readySources: MarketingAnalyticsSearchSource[]
    query: MarketingAnalyticsSearchQuery
}

export interface searchPerformanceLogicActions extends Pick<
    marketingAnalyticsLogicActions,
    'loadSources' | 'loadSourcesSuccess' | 'loadSourcesFailure'
> {
    setMetrics: (metrics: SearchMetrics) => { metrics: SearchMetrics }
    setSearch: (search: string) => { search: string }
    setQuerySearch: (search: string) => { search: string }
}

export type searchPerformanceLogicType = MakeLogicType<searchPerformanceLogicValues, searchPerformanceLogicActions>

export const searchPerformanceLogic = kea<searchPerformanceLogicType>([
    path(['products', 'marketingAnalytics', 'searchPerformanceLogic']),
    connect(() => ({
        values: [
            marketingAnalyticsLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading', 'dateFilter', 'compareFilter', 'integrationFilter'],
        ],
        actions: [marketingAnalyticsLogic, ['loadSources', 'loadSourcesSuccess', 'loadSourcesFailure']],
    })),
    actions({
        setMetrics: (metrics: SearchMetrics) => ({ metrics }),
        setSearch: (search: string) => ({ search }),
        setQuerySearch: (search: string) => ({ search }),
    }),
    reducers({
        metrics: ['traffic' as SearchMetrics, { setMetrics: (_, { metrics }) => metrics }],
        search: ['', { setSearch: (_, { search }) => search }],
        querySearch: ['', { setQuerySearch: (_, { search }) => search }],
        sourcesError: [
            false,
            { loadSources: () => false, loadSourcesSuccess: () => false, loadSourcesFailure: () => true },
        ],
    }),
    selectors({
        sources: [
            (s) => [s.dataWarehouseSources, s.integrationFilter],
            (response, integrationFilter): ExternalDataSource[] =>
                selectedSearchSources(response?.results ?? [], integrationFilter.integrationSourceIds ?? []),
        ],
        pendingSources: [
            (s) => [s.sources],
            (sources: ExternalDataSource[]): ExternalDataSource[] =>
                sources.filter((source) => !searchPerformanceSource(source)),
        ],
        readySources: [
            (s) => [s.sources],
            (sources: ExternalDataSource[]): MarketingAnalyticsSearchSource[] =>
                sources.flatMap((source) => {
                    const querySource = searchPerformanceSource(source)
                    return querySource ? [querySource] : []
                }),
        ],
        query: [
            (s) => [s.readySources, s.dateFilter, s.querySearch, s.compareFilter],
            (sources, dateFilter, search, compareFilter): MarketingAnalyticsSearchQuery => ({
                kind: NodeKind.MarketingAnalyticsSearchQuery,
                sources,
                compareFilter,
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                search,
            }),
        ],
    }),
    listeners(({ actions }) => ({
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(300)
            actions.setQuerySearch(search)
        },
    })),
    afterMount(({ values, actions }) => {
        if (!values.dataWarehouseSources) {
            actions.loadSources()
        }
    }),
])
