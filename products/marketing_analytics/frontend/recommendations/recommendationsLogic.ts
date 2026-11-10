import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import {
    RecommendationsEntryPoint,
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    IntegrationFilter,
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationResolutionState,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationsQuery,
    MarketingAnalyticsRecommendationsSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import {
    marketingAnalyticsRecommendationResolutionsCreate,
    marketingAnalyticsRecommendationResolutionsDestroy,
} from '../generated/api'
import { selectedSearchSources } from '../search/searchPerformance'
import {
    RECOMMENDATIONS_QUERY_KEY,
    RecommendationDataGap,
    ResolutionOverrides,
    recommendationDataGaps,
    recommendationKey,
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
    currentTeamId: number | null
    resolutionOverrides: ResolutionOverrides
    pendingKeys: string[]
    showResolved: boolean
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
    | 'reportRecommendationResolved'
    | 'reportRecommendationRestored'
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
    resolveRecommendation: (
        recommendation: MarketingAnalyticsRecommendation,
        resolution: MarketingAnalyticsRecommendationResolutionState
    ) => {
        recommendation: MarketingAnalyticsRecommendation
        resolution: MarketingAnalyticsRecommendationResolutionState
    }
    restoreRecommendation: (recommendation: MarketingAnalyticsRecommendation) => {
        recommendation: MarketingAnalyticsRecommendation
    }
    resolutionSaved: (
        key: string,
        resolution: MarketingAnalyticsRecommendationResolution
    ) => { key: string; resolution: MarketingAnalyticsRecommendationResolution }
    resolutionRemoved: (key: string) => { key: string }
    resolutionRequestFailed: (key: string) => { key: string }
    setShowResolved: (showResolved: boolean) => { showResolved: boolean }
}

export type recommendationsLogicType = MakeLogicType<recommendationsLogicValues, recommendationsLogicActions>

export const recommendationsLogic = kea<recommendationsLogicType>([
    path(['products', 'marketingAnalytics', 'recommendationsLogic']),
    connect(() => ({
        values: [
            marketingAnalyticsLogic,
            ['dataWarehouseSources', 'integrationFilter', 'dateFilter'],
            teamLogic,
            ['currentTeamId'],
        ],
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
                'reportRecommendationResolved',
                'reportRecommendationRestored',
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
        resolveRecommendation: (
            recommendation: MarketingAnalyticsRecommendation,
            resolution: MarketingAnalyticsRecommendationResolutionState
        ) => ({
            recommendation,
            resolution,
        }),
        restoreRecommendation: (recommendation: MarketingAnalyticsRecommendation) => ({ recommendation }),
        resolutionSaved: (key: string, resolution: MarketingAnalyticsRecommendationResolution) => ({
            key,
            resolution,
        }),
        resolutionRemoved: (key: string) => ({ key }),
        resolutionRequestFailed: (key: string) => ({ key }),
        setShowResolved: (showResolved: boolean) => ({ showResolved }),
    }),
    reducers({
        resolutionOverrides: [
            {} as ResolutionOverrides,
            {
                resolutionSaved: (state, { key, resolution }) => ({ ...state, [key]: resolution }),
                resolutionRemoved: (state, { key }) => ({ ...state, [key]: null }),
                // A new response carries the current resolutions, including ones made by other people.
                [dataNodeLogic({
                    key: RECOMMENDATIONS_QUERY_KEY,
                    query: { kind: NodeKind.MarketingAnalyticsRecommendationsQuery },
                }).actionTypes.loadDataSuccess]: () => ({}),
            },
        ],
        pendingKeys: [
            [] as string[],
            {
                resolveRecommendation: (state, { recommendation }) => [...state, recommendationKey(recommendation)],
                restoreRecommendation: (state, { recommendation }) => [...state, recommendationKey(recommendation)],
                resolutionSaved: (state, { key }) => state.filter((pending) => pending !== key),
                resolutionRemoved: (state, { key }) => state.filter((pending) => pending !== key),
                resolutionRequestFailed: (state, { key }) => state.filter((pending) => pending !== key),
            },
        ],
        showResolved: [
            false,
            { setShowResolved: (_, { showResolved }) => showResolved, closeRecommendations: () => false },
        ],
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
                // The modal lists resolved recommendations on request, and the counts leave them out.
                includeResolved: true,
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
    listeners(({ actions, selectors, values }) => ({
        resolveRecommendation: async ({ recommendation, resolution }) => {
            try {
                const saved = await marketingAnalyticsRecommendationResolutionsCreate(String(values.currentTeamId), {
                    ...recommendation.identity,
                    resolution,
                    snapshot: {
                        action: recommendation.action,
                        impact: recommendation.impact ?? null,
                        currency: recommendation.currency ?? null,
                    },
                })
                actions.resolutionSaved(recommendationKey(recommendation), {
                    id: saved.id,
                    state: saved.resolution,
                    resolvedAt: saved.resolved_at,
                })
                actions.reportRecommendationResolved(recommendation.rule, recommendation.level, resolution)
            } catch {
                actions.resolutionRequestFailed(recommendationKey(recommendation))
                lemonToast.error(
                    resolution === 'applied'
                        ? "Couldn't mark the recommendation as applied. Try again."
                        : "Couldn't dismiss the recommendation. Try again."
                )
            }
        },
        restoreRecommendation: async ({ recommendation }) => {
            const key = recommendationKey(recommendation)
            const resolution = recommendation.resolution
            if (!resolution) {
                actions.resolutionRemoved(key)
                return
            }
            try {
                await marketingAnalyticsRecommendationResolutionsDestroy(String(values.currentTeamId), resolution.id)
                actions.resolutionRemoved(key)
                actions.reportRecommendationRestored(recommendation.rule, recommendation.level, resolution.state)
            } catch (error) {
                // Someone else already restored it, so the local copy is stale rather than the request wrong.
                if (error instanceof ApiError && error.status === 404) {
                    actions.resolutionRemoved(key)
                    return
                }
                actions.resolutionRequestFailed(key)
                lemonToast.error("Couldn't restore the recommendation. Try again.")
            }
        },
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
