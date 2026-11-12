import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import {
    RecommendationsEntryPoint,
    RecommendationsShownState,
    marketingAnalyticsLogic,
    marketingAnalyticsLogicActions,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import {
    DataNodeLogicProps,
    dataNodeLogic,
    dataNodeLogicActions,
    dataNodeLogicValues,
} from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    IntegrationFilter,
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationResolutionState,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationsQuery,
    MarketingAnalyticsRecommendationsQueryResponse,
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
    RecommendationGroup,
    RecommendationSection,
    RecommendationTotal,
    ResolutionOverrides,
    groupRecommendations,
    reconcileResolutionOverrides,
    recommendationDataGaps,
    recommendationsShownState,
    recommendationsSource,
    sectionRecommendations,
    sumImpact,
    unresolved,
    withResolutionOverrides,
} from './recommendations'

const RECOMMENDATION_SOURCE_TYPES = ['GoogleAds', 'GoogleSearchConsole']
// Long enough to read the toast and reach Undo; Restore stays available after it closes.
const UNDO_TOAST_MS = 10000

// Only the key, so connecting finds the node the section mounts with its query instead of replacing that query.
const RECOMMENDATIONS_DATA_NODE = {
    key: RECOMMENDATIONS_QUERY_KEY,
    dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
} as DataNodeLogicProps

function responseRecommendations(response: dataNodeLogicValues['response']): MarketingAnalyticsRecommendation[] {
    return (response as MarketingAnalyticsRecommendationsQueryResponse | null)?.results ?? []
}

interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

export interface recommendationsLogicValues {
    response: dataNodeLogicValues['response']
    responseLoading: boolean
    responseError: string | null
    queryId: string | null
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
    disclaimer: string | undefined
    recommendations: MarketingAnalyticsRecommendation[]
    activeRecommendations: MarketingAnalyticsRecommendation[]
    resolvedCount: number
    totals: RecommendationTotal[]
    activeGroups: RecommendationGroup[]
    groups: RecommendationGroup[]
    sections: RecommendationSection[]
    firstRule: MarketingAnalyticsRecommendationRule | null
    selectedGroup: RecommendationGroup | null
    selectedGroupTotals: RecommendationTotal[]
    shownState: RecommendationsShownState | null
}

export interface recommendationsLogicActions
    extends
        Pick<dataNodeLogicActions, 'loadData' | 'loadDataSuccess'>,
        Pick<
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
    undoResolution: (
        recommendation: MarketingAnalyticsRecommendation,
        resolution: MarketingAnalyticsRecommendationResolution
    ) => { recommendation: MarketingAnalyticsRecommendation; resolution: MarketingAnalyticsRecommendationResolution }
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
            dataNodeLogic(RECOMMENDATIONS_DATA_NODE),
            ['response', 'responseLoading', 'responseError', 'queryId'],
        ],
        actions: [
            dataNodeLogic(RECOMMENDATIONS_DATA_NODE),
            ['loadData', 'loadDataSuccess'],
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
        undoResolution: (
            recommendation: MarketingAnalyticsRecommendation,
            resolution: MarketingAnalyticsRecommendationResolution
        ) => ({ recommendation, resolution }),
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
                loadDataSuccess: (state, { response }) =>
                    reconcileResolutionOverrides(state, responseRecommendations(response)),
            },
        ],
        pendingKeys: [
            [] as string[],
            {
                resolveRecommendation: (state, { recommendation }) => [...state, recommendation.key],
                restoreRecommendation: (state, { recommendation }) => [...state, recommendation.key],
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
                ...RECOMMENDATIONS_DATA_NODE,
                query,
            }),
        ],
        disclaimer: [
            (s) => [s.response],
            (response: dataNodeLogicValues['response']): string | undefined =>
                (response as MarketingAnalyticsRecommendationsQueryResponse | null)?.disclaimer,
        ],
        recommendations: [
            (s) => [s.response, s.resolutionOverrides],
            (
                response: dataNodeLogicValues['response'],
                resolutionOverrides: ResolutionOverrides
            ): MarketingAnalyticsRecommendation[] =>
                withResolutionOverrides(responseRecommendations(response), resolutionOverrides),
        ],
        activeRecommendations: [
            (s) => [s.recommendations],
            (recommendations: MarketingAnalyticsRecommendation[]): MarketingAnalyticsRecommendation[] =>
                unresolved(recommendations),
        ],
        resolvedCount: [
            (s) => [s.recommendations, s.activeRecommendations],
            (
                recommendations: MarketingAnalyticsRecommendation[],
                activeRecommendations: MarketingAnalyticsRecommendation[]
            ): number => recommendations.length - activeRecommendations.length,
        ],
        totals: [
            (s) => [s.activeRecommendations],
            (activeRecommendations: MarketingAnalyticsRecommendation[]): RecommendationTotal[] =>
                sumImpact(activeRecommendations),
        ],
        activeGroups: [
            (s) => [s.recommendations],
            (recommendations: MarketingAnalyticsRecommendation[]): RecommendationGroup[] =>
                groupRecommendations(recommendations, false, null),
        ],
        groups: [
            (s) => [s.recommendations, s.activeRecommendations, s.resolvedCount, s.showResolved, s.selectedRule],
            (
                recommendations: MarketingAnalyticsRecommendation[],
                activeRecommendations: MarketingAnalyticsRecommendation[],
                resolvedCount: number,
                showResolved: boolean,
                selectedRule: MarketingAnalyticsRecommendationRule | null
            ): RecommendationGroup[] =>
                groupRecommendations(
                    recommendations,
                    showResolved && resolvedCount > 0,
                    // With nothing left anywhere, the modal says so for every rule instead of one empty rule.
                    activeRecommendations.length > 0 ? selectedRule : null
                ),
        ],
        sections: [
            (s) => [s.groups],
            (groups: RecommendationGroup[]): RecommendationSection[] => sectionRecommendations(groups),
        ],
        firstRule: [
            (s) => [s.sections, s.recommendations],
            (
                sections: RecommendationSection[],
                recommendations: MarketingAnalyticsRecommendation[]
            ): MarketingAnalyticsRecommendationRule | null =>
                // With every recommendation resolved the modal still opens, so the resolved ones stay reachable.
                sections[0]?.groups[0]?.rule ?? recommendations[0]?.rule ?? null,
        ],
        selectedGroup: [
            (s) => [s.selectedRule, s.groups, s.sections],
            (
                selectedRule: MarketingAnalyticsRecommendationRule | null,
                groups: RecommendationGroup[],
                sections: RecommendationSection[]
            ): RecommendationGroup | null =>
                selectedRule === null
                    ? null
                    : // A new date range can drop the open rule, so the modal shows the first one instead of closing.
                      (groups.find((group) => group.rule === selectedRule) ?? sections[0]?.groups[0] ?? null),
        ],
        selectedGroupTotals: [
            (s) => [s.selectedGroup],
            (selectedGroup: RecommendationGroup | null): RecommendationTotal[] =>
                sumImpact(unresolved(selectedGroup?.recommendations ?? [])),
        ],
        shownState: [
            (s) => [
                s.dataWarehouseSources,
                s.responseLoading,
                s.responseError,
                s.connectedSourceTypes,
                s.sources,
                s.firstRule,
            ],
            (
                dataWarehouseSources: { results: ExternalDataSource[] } | null,
                responseLoading: boolean,
                responseError: string | null,
                connectedSourceTypes: string[],
                sources: MarketingAnalyticsRecommendationsSource[],
                firstRule: MarketingAnalyticsRecommendationRule | null
            ): RecommendationsShownState | null =>
                recommendationsShownState({
                    sourcesLoading: !dataWarehouseSources,
                    responseLoading,
                    responseError: !!responseError,
                    connectedSourceCount: connectedSourceTypes.length,
                    selectedSourceCount: sources.length,
                    hasRecommendations: !!firstRule,
                }),
        ],
    }),
    listeners(({ actions, selectors, values }) => ({
        resolveRecommendation: async ({ recommendation, resolution }) => {
            try {
                const saved = await marketingAnalyticsRecommendationResolutionsCreate(String(values.currentTeamId), {
                    identity: recommendation.identity,
                    resolution,
                    name: recommendation.subject,
                })
                actions.resolutionSaved(recommendation.key, saved)
                actions.reportRecommendationResolved(recommendation.rule, recommendation.level, resolution)
                lemonToast.success(
                    resolution === 'applied' ? 'Recommendation marked as applied' : 'Recommendation dismissed',
                    {
                        button: {
                            label: 'Undo',
                            action: () => actions.undoResolution(recommendation, saved),
                            dataAttr: 'marketing-recommendations-undo',
                        },
                        autoClose: UNDO_TOAST_MS,
                    }
                )
                // The freed slot of the rule fills with its next recommendation.
                actions.loadData()
            } catch {
                actions.resolutionRequestFailed(recommendation.key)
                lemonToast.error(
                    resolution === 'applied'
                        ? "Couldn't mark the recommendation as applied. Try again."
                        : "Couldn't dismiss the recommendation. Try again."
                )
            }
        },
        restoreRecommendation: async ({ recommendation }) => {
            const resolution = recommendation.resolution
            if (!resolution) {
                actions.resolutionRemoved(recommendation.key)
                return
            }
            try {
                await marketingAnalyticsRecommendationResolutionsDestroy(String(values.currentTeamId), resolution.id)
                actions.resolutionRemoved(recommendation.key)
                actions.reportRecommendationRestored(recommendation.rule, recommendation.level, resolution.resolution)
                actions.loadData()
            } catch (error) {
                // Someone else already restored it, so the local copy is stale rather than the request wrong.
                if (error instanceof ApiError && error.status === 404) {
                    actions.resolutionRemoved(recommendation.key)
                    actions.loadData()
                    return
                }
                actions.resolutionRequestFailed(recommendation.key)
                lemonToast.error("Couldn't restore the recommendation. Try again.")
            }
        },
        resolutionRemoved: () => {
            // With nothing resolved the toggle is hidden, so a later dismiss must hide its row again.
            if (values.showResolved && values.resolvedCount === 0) {
                actions.setShowResolved(false)
            }
        },
        undoResolution: ({ recommendation, resolution }) => {
            actions.reportRecommendationsActionClicked('undo', 'toast', recommendation.rule)
            actions.restoreRecommendation({ ...recommendation, resolution })
        },
        openRecommendations: ({ entryPoint, recommendationCount }) => {
            actions.reportRecommendationsOpened(entryPoint, recommendationCount)
        },
        selectRule: ({ rule, ruleRecommendationCount }, _, __, previousState) => {
            if (selectors.selectedGroup(previousState)?.rule !== rule) {
                actions.reportRecommendationsRuleSelected(rule, ruleRecommendationCount)
            }
        },
        closeRecommendations: (_, __, ___, previousState) => {
            actions.reportRecommendationsClosed(
                selectors.selectedGroup(previousState)?.rule ?? selectors.selectedRule(previousState)
            )
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
