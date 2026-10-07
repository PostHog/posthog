import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import {
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
    marketingAnalyticsLogicValues,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import {
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchRow,
    MarketingAnalyticsSearchSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import {
    SearchBreakdown,
    SearchChannel,
    SearchMetrics,
    SearchPlatform,
    selectedSearchSources,
    searchPerformanceSource,
    searchPerformanceSourceNotice,
} from './searchPerformance'

export interface searchPerformanceLogicValues extends Pick<
    marketingAnalyticsLogicValues,
    | 'dataWarehouseSources'
    | 'dataWarehouseSourcesLoading'
    | 'dateFilter'
    | 'compareFilter'
    | 'integrationFilter'
    | 'includeConversionGoals'
> {
    metrics: SearchMetrics
    hasPaidSources: boolean
    displayMetrics: SearchMetrics
    showPosition: boolean
    canShowPosition: boolean
    breakdown: SearchBreakdown
    channel: SearchChannel
    selectedRow: MarketingAnalyticsSearchRow | null
    detailQuery: MarketingAnalyticsSearchQuery | null
    allSearchSources: ExternalDataSource[]
    missingSources: SearchPlatform[]
    hasActiveFilters: boolean
    hasSearchConsole: boolean
    search: string
    querySearch: string
    sourcesError: boolean
    sources: ExternalDataSource[]
    sourceNotices: { sourceId: string; message: string }[]
    detailSourceNotices: { sourceId: string; message: string }[]
    detailSources: ExternalDataSource[]
    readySources: MarketingAnalyticsSearchSource[]
    query: MarketingAnalyticsSearchQuery
}

export interface searchPerformanceLogicActions extends Pick<
    marketingAnalyticsLogicActions,
    'loadSources' | 'loadSourcesSuccess' | 'loadSourcesFailure' | 'setIntegrationFilter' | 'setDates'
> {
    clearFilters: () => { value: true }
    setShowPosition: (showPosition: boolean) => { showPosition: boolean }
    setMetrics: (metrics: SearchMetrics) => { metrics: SearchMetrics }
    setBreakdown: (breakdown: SearchBreakdown) => { breakdown: SearchBreakdown }
    setChannel: (channel: SearchChannel) => { channel: SearchChannel }
    selectRow: (row: MarketingAnalyticsSearchRow | null) => { row: MarketingAnalyticsSearchRow | null }
    setSearch: (search: string) => { search: string }
    setQuerySearch: (search: string) => { search: string }
}

export type searchPerformanceLogicType = MakeLogicType<searchPerformanceLogicValues, searchPerformanceLogicActions>

export const searchPerformanceLogic = kea<searchPerformanceLogicType>([
    path(['products', 'marketingAnalytics', 'searchPerformanceLogic']),
    connect(() => ({
        values: [
            marketingAnalyticsLogic,
            [
                'dataWarehouseSources',
                'dataWarehouseSourcesLoading',
                'dateFilter',
                'compareFilter',
                'integrationFilter',
                'includeConversionGoals',
            ],
        ],
        actions: [
            marketingAnalyticsLogic,
            ['loadSources', 'loadSourcesSuccess', 'loadSourcesFailure', 'setIntegrationFilter', 'setDates'],
        ],
    })),
    actions({
        clearFilters: true,
        setMetrics: (metrics: SearchMetrics) => ({ metrics }),
        setShowPosition: (showPosition: boolean) => ({ showPosition }),
        setBreakdown: (breakdown: SearchBreakdown) => ({ breakdown }),
        setChannel: (channel: SearchChannel) => ({ channel }),
        selectRow: (row: MarketingAnalyticsSearchRow | null) => ({ row }),
        setSearch: (search: string) => ({ search }),
        setQuerySearch: (search: string) => ({ search }),
    }),
    reducers({
        breakdown: ['keyword' as SearchBreakdown, { setBreakdown: (_, { breakdown }) => breakdown }],
        channel: ['all' as SearchChannel, { setChannel: (_, { channel }) => channel }],
        selectedRow: [
            null as MarketingAnalyticsSearchRow | null,
            { selectRow: (_, { row }) => row, setBreakdown: () => null, setChannel: () => null },
        ],
        showPosition: [false, { setShowPosition: (_, { showPosition }) => showPosition }],
        metrics: ['traffic' as SearchMetrics, { setMetrics: (_, { metrics }) => metrics }],
        search: ['', { setSearch: (_, { search }) => search }],
        querySearch: ['', { setQuerySearch: (_, { search }) => search }],
        sourcesError: [
            false,
            { loadSources: () => false, loadSourcesSuccess: () => false, loadSourcesFailure: () => true },
        ],
    }),
    selectors({
        allSearchSources: [
            (s) => [s.dataWarehouseSources],
            (response): ExternalDataSource[] => selectedSearchSources(response?.results ?? [], []),
        ],
        missingSources: [
            (s) => [s.allSearchSources],
            (sources: ExternalDataSource[]): SearchPlatform[] =>
                (['GoogleAds', 'GoogleSearchConsole'] as SearchPlatform[]).filter(
                    (type) => !sources.some((source) => source.source_type === type)
                ),
        ],
        hasActiveFilters: [
            (s) => [s.querySearch, s.channel, s.integrationFilter, s.dateFilter, s.allSearchSources],
            (search, channel, filter, dates, sources: ExternalDataSource[]): boolean => {
                const ids = filter.integrationSourceIds ?? []
                const allSourcesSelected = sources.length > 0 && sources.every((source) => ids.includes(source.id))
                return (
                    !!search.trim() ||
                    channel !== 'all' ||
                    (ids.length > 0 && !allSourcesSelected) ||
                    dates.dateFrom !== '-7d' ||
                    !!dates.dateTo
                )
            },
        ],
        hasSearchConsole: [
            (s) => [s.allSearchSources],
            (sources: ExternalDataSource[]): boolean =>
                sources.some((source) => source.source_type === 'GoogleSearchConsole'),
        ],
        sources: [
            (s) => [s.allSearchSources, s.integrationFilter, s.channel],
            (allSources, integrationFilter, channel): ExternalDataSource[] =>
                selectedSearchSources(allSources, integrationFilter.integrationSourceIds ?? []).filter(
                    (source) =>
                        channel === 'all' ||
                        (source.source_type === 'GoogleSearchConsole' ? channel === 'organic' : channel === 'paid')
                ),
        ],
        sourceNotices: [
            (s) => [s.sources, s.breakdown],
            (sources: ExternalDataSource[], breakdown): { sourceId: string; message: string }[] =>
                sources.flatMap((source) => {
                    const message = searchPerformanceSourceNotice(source, breakdown)
                    return message ? [{ sourceId: source.id, message }] : []
                }),
        ],
        readySources: [
            (s) => [s.sources, s.breakdown],
            (sources: ExternalDataSource[], breakdown): MarketingAnalyticsSearchSource[] =>
                sources.flatMap((source) => {
                    const querySource = searchPerformanceSource(source, breakdown)
                    return querySource ? [querySource] : []
                }),
        ],
        hasPaidSources: [
            (s) => [s.readySources],
            (sources: MarketingAnalyticsSearchSource[]): boolean =>
                sources.some((source) => source.sourceType !== 'GoogleSearchConsole'),
        ],
        displayMetrics: [
            (s) => [s.hasPaidSources, s.metrics, s.breakdown],
            (hasPaidSources: boolean, metrics: SearchMetrics, breakdown): SearchMetrics =>
                hasPaidSources || breakdown === 'page' ? metrics : 'traffic',
        ],
        canShowPosition: [
            (s) => [s.readySources, s.metrics],
            (sources: MarketingAnalyticsSearchSource[], metrics: SearchMetrics): boolean =>
                metrics === 'traffic' &&
                sources.some((source) => source.sourceType === 'GoogleSearchConsole') &&
                sources.some((source) => source.sourceType !== 'GoogleSearchConsole'),
        ],
        query: [
            (s) => [
                s.readySources,
                s.dateFilter,
                s.querySearch,
                s.compareFilter,
                s.breakdown,
                s.includeConversionGoals,
                s.displayMetrics,
            ],
            (
                sources,
                dateFilter,
                search,
                compareFilter,
                breakdown,
                includeConversionGoals,
                metrics
            ): MarketingAnalyticsSearchQuery => ({
                kind: NodeKind.MarketingAnalyticsSearchQuery,
                sources,
                breakdown,
                compareFilter,
                includePostHogConversions: breakdown === 'page' && metrics === 'conversions' && includeConversionGoals,
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                search,
            }),
        ],
        detailSources: [
            (s) => [s.allSearchSources, s.integrationFilter, s.selectedRow],
            (allSources: ExternalDataSource[], integrationFilter, row): ExternalDataSource[] =>
                (row?.platform === 'GoogleSearchConsole'
                    ? selectedSearchSources(allSources, integrationFilter.integrationSourceIds ?? [])
                    : allSources
                ).filter((source) => source.source_type === 'GoogleSearchConsole'),
        ],
        detailSourceNotices: [
            (s) => [s.detailSources],
            (sources: ExternalDataSource[]): { sourceId: string; message: string }[] =>
                sources.flatMap((source) => {
                    const message = searchPerformanceSourceNotice(source, 'keyword', true)
                    return message ? [{ sourceId: source.id, message }] : []
                }),
        ],
        detailQuery: [
            (s) => [s.detailSources, s.selectedRow, s.query],
            (sources: ExternalDataSource[], row, query): MarketingAnalyticsSearchQuery | null => {
                if (!row || !(row.page || row.keyword)) {
                    return null
                }
                const detailSources = sources.flatMap((source) => {
                    const detailSource = searchPerformanceSource(source, row.page ? 'keyword' : 'page', true)
                    return detailSource ? [detailSource] : []
                })
                return {
                    ...query,
                    includePostHogConversions: false,
                    sources: detailSources,
                    search: undefined,
                    breakdown: row.page ? 'keyword' : 'page',
                    keyword: row.page ? undefined : (row.keyword ?? undefined),
                    page: row.page ?? undefined,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        clearFilters: () => {
            actions.setSearch('')
            actions.setQuerySearch('')
            actions.setChannel('all')
            actions.setIntegrationFilter({ ...values.integrationFilter, integrationSourceIds: [] })
            actions.setDates('-7d', null)
        },
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
