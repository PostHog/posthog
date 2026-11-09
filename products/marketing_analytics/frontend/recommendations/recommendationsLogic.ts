import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import {
    RecommendationsEntryPoint,
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    IntegrationFilter,
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationsQuery,
    MarketingAnalyticsRecommendationsSource,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

import {
    marketingAnalyticsRecommendationDismissalsCreate,
    marketingAnalyticsRecommendationDismissalsDestroy,
    marketingAnalyticsRecommendationDismissalsList,
} from '../generated/api'
import { RecommendationDismissalApi } from '../generated/api.schemas'
import { selectedSearchSources } from '../search/searchPerformance'
import {
    RECOMMENDATIONS_QUERY_KEY,
    RecommendationDataGap,
    dismissalFields,
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
    dismissals: RecommendationDismissalApi[] | null
    dismissalsLoading: boolean
    dismissedKeys: Set<string>
    pendingKeys: string[]
    showDismissed: boolean
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
    | 'reportRecommendationDismissed'
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
    loadDismissals: () => void
    loadDismissalsSuccess: (
        dismissals: RecommendationDismissalApi[] | null,
        payload?: any
    ) => { dismissals: RecommendationDismissalApi[] | null; payload?: any }
    loadDismissalsFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    dismissRecommendation: (recommendation: MarketingAnalyticsRecommendation) => {
        recommendation: MarketingAnalyticsRecommendation
    }
    restoreRecommendation: (recommendation: MarketingAnalyticsRecommendation) => {
        recommendation: MarketingAnalyticsRecommendation
    }
    dismissalSaved: (dismissal: RecommendationDismissalApi) => { dismissal: RecommendationDismissalApi }
    dismissalRemoved: (key: string) => { key: string }
    dismissalRequestFailed: (key: string) => { key: string }
    setShowDismissed: (showDismissed: boolean) => { showDismissed: boolean }
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
                'reportRecommendationDismissed',
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
        dismissRecommendation: (recommendation: MarketingAnalyticsRecommendation) => ({ recommendation }),
        restoreRecommendation: (recommendation: MarketingAnalyticsRecommendation) => ({ recommendation }),
        dismissalSaved: (dismissal: RecommendationDismissalApi) => ({ dismissal }),
        dismissalRemoved: (key: string) => ({ key }),
        dismissalRequestFailed: (key: string) => ({ key }),
        setShowDismissed: (showDismissed: boolean) => ({ showDismissed }),
    }),
    loaders(({ values }) => ({
        dismissals: [
            null as RecommendationDismissalApi[] | null,
            {
                loadDismissals: async () =>
                    await marketingAnalyticsRecommendationDismissalsList(String(values.currentTeamId)),
            },
        ],
    })),
    reducers({
        dismissals: {
            dismissalSaved: (state, { dismissal }) => [
                ...(state ?? []).filter((existing) => existing.id !== dismissal.id),
                dismissal,
            ],
            dismissalRemoved: (state, { key }) =>
                (state ?? []).filter((dismissal) => recommendationKey(dismissal) !== key),
        },
        pendingKeys: [
            [] as string[],
            {
                dismissRecommendation: (state, { recommendation }) => [...state, recommendationKey(recommendation)],
                restoreRecommendation: (state, { recommendation }) => [...state, recommendationKey(recommendation)],
                dismissalSaved: (state, { dismissal }) => state.filter((key) => key !== recommendationKey(dismissal)),
                dismissalRemoved: (state, { key }) => state.filter((pending) => pending !== key),
                dismissalRequestFailed: (state, { key }) => state.filter((pending) => pending !== key),
            },
        ],
        showDismissed: [
            false,
            { setShowDismissed: (_, { showDismissed }) => showDismissed, closeRecommendations: () => false },
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
        dismissedKeys: [
            (s) => [s.dismissals],
            (dismissals: RecommendationDismissalApi[] | null): Set<string> =>
                new Set((dismissals ?? []).map(recommendationKey)),
        ],
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
    listeners(({ actions, selectors, values }) => ({
        dismissRecommendation: async ({ recommendation }) => {
            try {
                const dismissal = await marketingAnalyticsRecommendationDismissalsCreate(
                    String(values.currentTeamId),
                    dismissalFields(recommendation)
                )
                actions.dismissalSaved(dismissal)
                actions.reportRecommendationDismissed(recommendation.rule, recommendation.level)
            } catch {
                actions.dismissalRequestFailed(recommendationKey(recommendation))
                lemonToast.error("Couldn't dismiss the recommendation. Try again.")
            }
        },
        restoreRecommendation: async ({ recommendation }) => {
            const key = recommendationKey(recommendation)
            const dismissal = values.dismissals?.find((existing) => recommendationKey(existing) === key)
            if (!dismissal) {
                actions.dismissalRemoved(key)
                return
            }
            try {
                await marketingAnalyticsRecommendationDismissalsDestroy(String(values.currentTeamId), dismissal.id)
                actions.dismissalRemoved(key)
                actions.reportRecommendationRestored(recommendation.rule, recommendation.level)
            } catch {
                actions.dismissalRequestFailed(key)
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
        actions.loadDismissals()
    }),
])
