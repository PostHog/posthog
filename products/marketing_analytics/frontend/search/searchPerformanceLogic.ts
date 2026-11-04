import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic, featureFlagLogicValues } from 'lib/logic/featureFlagLogic'
import { teamLogic, teamLogicActions } from 'scenes/teamLogic'
import {
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
    marketingAnalyticsLogicValues,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    ConversionGoalFilter,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchRow,
    MarketingAnalyticsSearchSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { externalDataSourcesBulkUpdateSchemasPartialUpdate } from 'products/warehouse_sources/frontend/generated/api'

import {
    CampaignChannelTypes,
    SEARCH_PERFORMANCE_QUERY_KEY,
    SearchBreakdown,
    SearchChannel,
    SearchMetrics,
    SearchNoticeKind,
    SearchPlatform,
    campaignChannelTypesQuery,
    selectedSearchSources,
    searchPerformanceSource,
    searchPerformanceSourceNotice,
    searchSourceName,
    searchTermTablesToEnable,
} from './searchPerformance'

export interface SearchSourceNotice {
    sourceId: string
    sourceType: string
    name: string
    message: string
    kind: SearchNoticeKind
    /** Disabled tables the notice offers to enable. Enabling one starts a billed sync of its full history. */
    enableSchemaIds: string[]
    enableButtonLabel: string
}

export interface searchPerformanceLogicValues extends Pick<
    marketingAnalyticsLogicValues,
    | 'dataWarehouseSources'
    | 'dataWarehouseSourcesLoading'
    | 'dateFilter'
    | 'compareFilter'
    | 'integrationFilter'
    | 'includeConversionGoals'
    | 'conversion_goals'
> {
    featureFlags: featureFlagLogicValues['featureFlags']
    searchConversionsEnabled: boolean
    includeSearchConversionGoals: boolean
    wrapText: boolean
    metrics: SearchMetrics
    hasPaidSources: boolean
    conversionsDisabledReason: string | null
    displayMetrics: SearchMetrics
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
    campaignChannelTypes: CampaignChannelTypes | null
    campaignChannelTypesLoading: boolean
    enablingSourceIds: string[]
    sourceNotices: SearchSourceNotice[]
    detailSourceNotices: SearchSourceNotice[]
    detailSources: ExternalDataSource[]
    readySources: MarketingAnalyticsSearchSource[]
    query: MarketingAnalyticsSearchQuery
}

export interface searchPerformanceLogicActions
    extends
        Pick<
            marketingAnalyticsLogicActions,
            'loadSources' | 'loadSourcesSuccess' | 'loadSourcesFailure' | 'setIntegrationFilter' | 'setDates'
        >,
        Pick<teamLogicActions, 'updateCurrentTeamSuccess'> {
    setWrapText: (wrapText: boolean) => { wrapText: boolean }
    clearFilters: () => { value: true }
    setMetrics: (metrics: SearchMetrics) => { metrics: SearchMetrics }
    setBreakdown: (breakdown: SearchBreakdown) => { breakdown: SearchBreakdown }
    setChannel: (channel: SearchChannel) => { channel: SearchChannel }
    selectRow: (row: MarketingAnalyticsSearchRow | null) => { row: MarketingAnalyticsSearchRow | null }
    setSearch: (search: string) => { search: string }
    setQuerySearch: (search: string) => { search: string }
    loadCampaignChannelTypes: () => void
    loadCampaignChannelTypesSuccess: (
        campaignChannelTypes: CampaignChannelTypes | null,
        payload?: any
    ) => { campaignChannelTypes: CampaignChannelTypes | null; payload?: any }
    loadCampaignChannelTypesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    enableSearchTermTables: (sourceId: string, schemaIds: string[]) => { sourceId: string; schemaIds: string[] }
    enableSearchTermTablesFinished: (sourceId: string) => { sourceId: string }
}

export type searchPerformanceLogicType = MakeLogicType<searchPerformanceLogicValues, searchPerformanceLogicActions>

export const searchPerformanceLogic = kea<searchPerformanceLogicType>([
    path(['products', 'marketingAnalytics', 'searchPerformanceLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            marketingAnalyticsLogic,
            [
                'dataWarehouseSources',
                'dataWarehouseSourcesLoading',
                'dateFilter',
                'compareFilter',
                'integrationFilter',
                'includeConversionGoals',
                'conversion_goals',
            ],
        ],
        actions: [
            marketingAnalyticsLogic,
            ['loadSources', 'loadSourcesSuccess', 'loadSourcesFailure', 'setIntegrationFilter', 'setDates'],
            teamLogic,
            ['updateCurrentTeamSuccess'],
        ],
    })),
    actions({
        setWrapText: (wrapText: boolean) => ({ wrapText }),
        clearFilters: true,
        setMetrics: (metrics: SearchMetrics) => ({ metrics }),
        setBreakdown: (breakdown: SearchBreakdown) => ({ breakdown }),
        setChannel: (channel: SearchChannel) => ({ channel }),
        selectRow: (row: MarketingAnalyticsSearchRow | null) => ({ row }),
        setSearch: (search: string) => ({ search }),
        setQuerySearch: (search: string) => ({ search }),
        enableSearchTermTables: (sourceId: string, schemaIds: string[]) => ({ sourceId, schemaIds }),
        enableSearchTermTablesFinished: (sourceId: string) => ({ sourceId }),
    }),
    loaders(({ values }) => ({
        campaignChannelTypes: [
            null as CampaignChannelTypes | null,
            {
                loadCampaignChannelTypes: async (_, breakpoint) => {
                    const entries = await Promise.all(
                        values.allSearchSources.map(async (source): Promise<[string, string[]] | null> => {
                            const query = campaignChannelTypesQuery(source)
                            if (!query) {
                                return null
                            }
                            try {
                                const response = await api.queryHogQL<[string[]][]>(query, {
                                    productKey: 'marketing_analytics',
                                    name: 'marketing_search_campaign_channel_types',
                                })
                                return [source.id, response.results[0]?.[0] ?? []]
                            } catch {
                                // An unknown campaign mix asks for no tables rather than guessing.
                                return null
                            }
                        })
                    )
                    breakpoint()
                    return Object.fromEntries(entries.filter((entry): entry is [string, string[]] => !!entry))
                },
            },
        ],
    })),
    reducers({
        enablingSourceIds: [
            [] as string[],
            {
                enableSearchTermTables: (state, { sourceId }) => [...state, sourceId],
                enableSearchTermTablesFinished: (state, { sourceId }) => state.filter((id) => id !== sourceId),
            },
        ],
        wrapText: [false, { setWrapText: (_, { wrapText }) => wrapText }],
        breakdown: ['keyword' as SearchBreakdown, { setBreakdown: (_, { breakdown }) => breakdown }],
        channel: ['all' as SearchChannel, { setChannel: (_, { channel }) => channel }],
        selectedRow: [
            null as MarketingAnalyticsSearchRow | null,
            { selectRow: (_, { row }) => row, setBreakdown: () => null, setChannel: () => null },
        ],
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
            (s) => [s.sources, s.breakdown, s.campaignChannelTypes],
            (
                sources: ExternalDataSource[],
                breakdown,
                campaignChannelTypes: CampaignChannelTypes | null
            ): SearchSourceNotice[] =>
                sources.flatMap((source) => {
                    const channelTypes = campaignChannelTypes?.[source.id]
                    const notice = searchPerformanceSourceNotice(source, breakdown, false, channelTypes)
                    if (!notice) {
                        return []
                    }
                    const { schemaIds: enableSchemaIds, buttonLabel: enableButtonLabel } =
                        breakdown === 'search_term' && channelTypes
                            ? searchTermTablesToEnable(source, channelTypes)
                            : { schemaIds: [], buttonLabel: '' }
                    return [
                        {
                            sourceId: source.id,
                            sourceType: source.source_type,
                            name: searchSourceName(source),
                            ...notice,
                            enableSchemaIds,
                            enableButtonLabel,
                        },
                    ]
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
        searchConversionsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SEARCH_CONVERSIONS],
        ],
        includeSearchConversionGoals: [
            (s) => [s.searchConversionsEnabled, s.includeConversionGoals],
            (enabled, includeConversionGoals): boolean => enabled && includeConversionGoals,
        ],
        conversionsDisabledReason: [
            (s) => [
                s.hasPaidSources,
                s.breakdown,
                s.includeSearchConversionGoals,
                s.conversion_goals,
                s.searchConversionsEnabled,
            ],
            (
                hasPaidSources: boolean,
                breakdown: SearchBreakdown,
                includeConversionGoals: boolean,
                conversionGoals: ConversionGoalFilter[],
                enabled: boolean
            ): string | null => {
                if (hasPaidSources || (breakdown === 'page' && includeConversionGoals)) {
                    return null
                }
                if (!enabled || breakdown !== 'page') {
                    return 'Reported conversions require synced ad platform data. Check your source settings or filters. Google Search Console only reports organic traffic.'
                }
                return conversionGoals.length > 0
                    ? 'Turn on "Include conversion goals" to see PostHog conversions for organic landing pages.'
                    : 'Configure a conversion goal in marketing analytics settings to see PostHog conversions for organic landing pages.'
            },
        ],
        displayMetrics: [
            (s) => [s.conversionsDisabledReason, s.metrics],
            (conversionsDisabledReason: string | null, metrics: SearchMetrics): SearchMetrics =>
                conversionsDisabledReason ? 'traffic' : metrics,
        ],
        query: [
            (s) => [
                s.readySources,
                s.dateFilter,
                s.querySearch,
                s.compareFilter,
                s.breakdown,
                s.includeSearchConversionGoals,
                s.displayMetrics,
            ],
            (
                sources: MarketingAnalyticsSearchSource[],
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
                includePostHogConversions:
                    metrics === 'conversions' &&
                    includeConversionGoals &&
                    breakdown !== 'search_term' &&
                    (breakdown === 'page' || sources.some((source) => source.sourceType !== 'GoogleSearchConsole')),
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
            (sources: ExternalDataSource[]): SearchSourceNotice[] =>
                sources.flatMap((source) => {
                    const notice = searchPerformanceSourceNotice(source, 'keyword', true)
                    return notice
                        ? [
                              {
                                  sourceId: source.id,
                                  sourceType: source.source_type,
                                  name: searchSourceName(source),
                                  ...notice,
                                  enableSchemaIds: [],
                                  enableButtonLabel: '',
                              },
                          ]
                        : []
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
                    normalizePageUrls: query.includePostHogConversions,
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
        setBreakdown: ({ breakdown }) => {
            if (breakdown === 'search_term') {
                actions.loadCampaignChannelTypes()
            }
        },
        loadSourcesSuccess: () => {
            if (values.breakdown === 'search_term') {
                actions.loadCampaignChannelTypes()
            }
        },
        enableSearchTermTables: async ({ sourceId, schemaIds }) => {
            try {
                await externalDataSourcesBulkUpdateSchemasPartialUpdate(
                    String(ApiConfig.getCurrentProjectId()),
                    sourceId,
                    { schemas: schemaIds.map((id) => ({ id, should_sync: true, apply_sync_defaults: true })) }
                )
                lemonToast.success('Sync started. Search terms will appear when the first sync finishes.')
                actions.loadSources()
            } catch (error: any) {
                lemonToast.error(
                    `Could not enable the tables. ${error?.detail ?? 'Try again from the source settings.'}`
                )
            } finally {
                actions.enableSearchTermTablesFinished(sourceId)
            }
        },
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(300)
            actions.setQuerySearch(search)
        },
        updateCurrentTeamSuccess: ({ payload }) => {
            // The backend reads the saved test-account setting, which the query does not carry, so a
            // changed setting leaves the cached goal columns stale until the table reloads past the cache.
            if (
                values.query.includePostHogConversions &&
                payload?.marketing_analytics_config &&
                'filter_test_accounts' in payload.marketing_analytics_config
            ) {
                dataNodeLogic.findMounted({ key: SEARCH_PERFORMANCE_QUERY_KEY })?.actions.loadData('force_async')
            }
        },
    })),
    afterMount(({ values, actions }) => {
        if (!values.dataWarehouseSources) {
            actions.loadSources()
        }
    }),
])
