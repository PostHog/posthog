import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import {
    RecommendationsEntryPoint,
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    IntegrationFilter,
    MarketingAnalyticsRecommendationRule,
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
    selectedRule: MarketingAnalyticsRecommendationRule | null
    introSeen: boolean
}

export interface recommendationsLogicActions extends Pick<
    marketingAnalyticsLogicActions,
    | 'loadSources'
    | 'reportRecommendationsShown'
    | 'reportRecommendationsOpened'
    | 'reportRecommendationsIntroDismissed'
    | 'reportRecommendationsRuleSelected'
    | 'reportRecommendationsClosed'
    | 'reportRecommendationsActionClicked'
> {
    openRecommendations: (
        rule: MarketingAnalyticsRecommendationRule,
        entryPoint: RecommendationsEntryPoint,
        recommendationCount: number
    ) => {
        rule: MarketingAnalyticsRecommendationRule
        entryPoint: RecommendationsEntryPoint
        recommendationCount: number
    }
    selectRule: (
        rule: MarketingAnalyticsRecommendationRule,
        ruleRecommendationCount: number
    ) => { rule: MarketingAnalyticsRecommendationRule; ruleRecommendationCount: number }
    closeRecommendations: () => { value: true }
    dismissIntro: () => { value: true }
}

export type recommendationsLogicType = MakeLogicType<recommendationsLogicValues, recommendationsLogicActions>

export const recommendationsLogic = kea<recommendationsLogicType>([
    path(['products', 'marketingAnalytics', 'recommendationsLogic']),
    connect(() => ({
        values: [marketingAnalyticsLogic, ['dataWarehouseSources', 'integrationFilter', 'dateFilter']],
        actions: [
            marketingAnalyticsLogic,
            [
                'loadSources',
                'reportRecommendationsShown',
                'reportRecommendationsOpened',
                'reportRecommendationsIntroDismissed',
                'reportRecommendationsRuleSelected',
                'reportRecommendationsClosed',
                'reportRecommendationsActionClicked',
            ],
        ],
    })),
    actions({
        openRecommendations: (
            rule: MarketingAnalyticsRecommendationRule,
            entryPoint: RecommendationsEntryPoint,
            recommendationCount: number
        ) => ({ rule, entryPoint, recommendationCount }),
        selectRule: (rule: MarketingAnalyticsRecommendationRule, ruleRecommendationCount: number) => ({
            rule,
            ruleRecommendationCount,
        }),
        closeRecommendations: true,
        dismissIntro: true,
    }),
    reducers({
        selectedRule: [
            null as MarketingAnalyticsRecommendationRule | null,
            {
                openRecommendations: (_, { rule }) => rule,
                selectRule: (_, { rule }) => rule,
                closeRecommendations: () => null,
            },
        ],
        // pinned: persisted under this reducer name, renaming it shows the intro again to everyone who closed it
        introSeen: [false, { persist: true }, { dismissIntro: () => true, openRecommendations: () => true }],
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
    listeners(({ actions, selectors }) => ({
        openRecommendations: ({ entryPoint, recommendationCount }) => {
            actions.reportRecommendationsOpened(entryPoint, recommendationCount)
        },
        selectRule: ({ rule, ruleRecommendationCount }) => {
            actions.reportRecommendationsRuleSelected(rule, ruleRecommendationCount)
        },
        closeRecommendations: (_, __, ___, previousState) => {
            actions.reportRecommendationsClosed(selectors.selectedRule(previousState))
        },
        dismissIntro: () => {
            actions.reportRecommendationsIntroDismissed()
        },
    })),
    afterMount(({ values, actions }) => {
        if (!values.dataWarehouseSources) {
            actions.loadSources()
        }
    }),
])
