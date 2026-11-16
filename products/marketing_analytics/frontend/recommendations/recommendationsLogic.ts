import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    IntegrationFilter,
    MarketingAnalyticsRecommendationsQuery,
    MarketingAnalyticsRecommendationsSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import { selectedSearchSources } from '../search/searchPerformance'
import {
    RECOMMENDATIONS_QUERY_KEY,
    RecommendationDataGap,
    recommendationDataGaps,
    recommendationsSource,
} from './recommendations'

const RECOMMENDATION_SOURCE_TYPES = ['GoogleAds', 'GoogleSearchConsole']

interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

export interface recommendationsLogicValues {
    dataWarehouseSources: { results: ExternalDataSource[] } | null
    integrationFilter: IntegrationFilter
    dateFilter: DateFilter
    selectedSources: ExternalDataSource[]
    sources: MarketingAnalyticsRecommendationsSource[]
    dataGaps: RecommendationDataGap[]
    hasAdsSource: boolean
    connectedSourceTypes: string[]
    query: MarketingAnalyticsRecommendationsQuery
    dataNodeProps: DataNodeLogicProps
    selectedRule: string | null
    introSeen: boolean
}

export interface recommendationsLogicActions {
    loadSources: () => void
    setSelectedRule: (rule: string | null) => { rule: string | null }
    dismissIntro: () => { value: true }
}

export type recommendationsLogicType = MakeLogicType<recommendationsLogicValues, recommendationsLogicActions>

export const recommendationsLogic = kea<recommendationsLogicType>([
    path(['products', 'marketingAnalytics', 'recommendationsLogic']),
    connect(() => ({
        values: [marketingAnalyticsLogic, ['dataWarehouseSources', 'integrationFilter', 'dateFilter']],
        actions: [marketingAnalyticsLogic, ['loadSources']],
    })),
    actions({
        setSelectedRule: (rule: string | null) => ({ rule }),
        dismissIntro: true,
    }),
    reducers({
        selectedRule: [null as string | null, { setSelectedRule: (_, { rule }) => rule }],
        // pinned: persisted under this reducer name, renaming it shows the intro again to everyone who closed it
        introSeen: [
            false,
            { persist: true },
            { dismissIntro: () => true, setSelectedRule: (seen, { rule }) => seen || rule !== null },
        ],
    }),
    selectors({
        selectedSources: [
            (s) => [s.dataWarehouseSources, s.integrationFilter],
            (
                dataWarehouseSources: { results: ExternalDataSource[] } | null,
                integrationFilter: IntegrationFilter
            ): ExternalDataSource[] =>
                selectedSearchSources(
                    dataWarehouseSources?.results ?? [],
                    integrationFilter.integrationSourceIds ?? [],
                    RECOMMENDATION_SOURCE_TYPES
                ),
        ],
        sources: [
            (s) => [s.selectedSources],
            (selectedSources: ExternalDataSource[]): MarketingAnalyticsRecommendationsSource[] =>
                selectedSources.flatMap((source) => recommendationsSource(source) ?? []),
        ],
        dataGaps: [
            (s) => [s.selectedSources],
            (selectedSources: ExternalDataSource[]): RecommendationDataGap[] =>
                selectedSources.flatMap(recommendationDataGaps),
        ],
        connectedSourceTypes: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources: { results: ExternalDataSource[] } | null): string[] =>
                (dataWarehouseSources?.results ?? [])
                    .map((source) => source.source_type)
                    .filter((type) => RECOMMENDATION_SOURCE_TYPES.includes(type)),
        ],
        hasAdsSource: [
            (s) => [s.sources],
            (sources: MarketingAnalyticsRecommendationsSource[]): boolean =>
                sources.some((source) => source.sourceType === 'GoogleAds'),
        ],
        query: [
            (s) => [s.sources, s.dateFilter],
            (
                sources: MarketingAnalyticsRecommendationsSource[],
                dateFilter: DateFilter
            ): MarketingAnalyticsRecommendationsQuery => ({
                kind: NodeKind.MarketingAnalyticsRecommendationsQuery,
                sources,
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
            }),
        ],
        dataNodeProps: [
            (s) => [s.query],
            (query: MarketingAnalyticsRecommendationsQuery): DataNodeLogicProps => ({
                key: RECOMMENDATIONS_QUERY_KEY,
                query,
                dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
            }),
        ],
    }),
    afterMount(({ values, actions }) => {
        if (!values.dataWarehouseSources) {
            actions.loadSources()
        }
    }),
])
