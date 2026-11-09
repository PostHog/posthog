import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonSkeleton, Popover } from '@posthog/lemon-ui'

import { RecommendationsShownState } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRecommendationsQueryResponse } from '~/queries/schema/schema-general'

import { MarketingQueryError } from '../dashboard/MarketingQueryError'
import {
    groupRecommendations,
    recommendationsShownState,
    sectionRecommendations,
    sumImpact,
    withoutDismissed,
} from './recommendations'
import { RecommendationsIdle } from './RecommendationsIdle'
import { recommendationsLogic } from './recommendationsLogic'
import { RecommendationsModal } from './RecommendationsModal'
import { RecommendationsSummary } from './RecommendationsSummary'

export function RecommendationsSection(): JSX.Element {
    const {
        dataNodeProps,
        dataWarehouseSources,
        sources,
        dataGaps,
        selectedRule,
        introSeen,
        connectedSourceTypes,
        dismissedKeys,
        showDismissed,
        dismissals,
        dismissalsLoading,
    } = useValues(recommendationsLogic)
    const { openRecommendations, selectRule, closeRecommendations, dismissIntro, reportRecommendationsShown } =
        useActions(recommendationsLogic)
    const { response, responseLoading, responseError, queryId } = useValues(dataNodeLogic(dataNodeProps))
    const { loadData } = useActions(dataNodeLogic(dataNodeProps))

    const recommendationsResponse = response as MarketingAnalyticsRecommendationsQueryResponse | null
    const allResults = recommendationsResponse?.results ?? []
    const results = withoutDismissed(allResults, dismissedKeys)
    const dismissedCount = allResults.length - results.length
    const visibleGroups = groupRecommendations(results)
    const groups = showDismissed && dismissedCount > 0 ? groupRecommendations(allResults) : visibleGroups
    const sections = sectionRecommendations(groups)
    // With every recommendation dismissed the modal still opens, so the dismissed ones stay reachable.
    const firstRule = sections[0]?.groups[0]?.rule ?? allResults[0]?.rule
    // Reloading can drop the open rule, so the modal falls back to the first one instead of closing on its own.
    const selectedGroup =
        selectedRule === null
            ? undefined
            : (groups.find((group) => group.rule === selectedRule) ?? sections[0]?.groups[0])
    // Until dismissals load, a dismissed recommendation would flash back into the list.
    const dismissalsPending = dismissalsLoading && dismissals === null
    const shownState = recommendationsShownState({
        sourcesLoading: !dataWarehouseSources,
        dismissalsPending,
        responseLoading,
        responseError: !!responseError,
        connectedSourceCount: connectedSourceTypes.length,
        selectedSourceCount: sources.length,
        hasRecommendations: !!firstRule,
    })
    const showGroups = shownState === 'recommendations'
    const openFirstRule = (source: 'intro' | 'button'): void => {
        if (firstRule) {
            openRecommendations(firstRule, source, results.length)
        }
    }

    const reportedState = useRef<RecommendationsShownState | null>(null)
    useEffect(() => {
        if (!shownState || shownState === reportedState.current) {
            return
        }
        reportedState.current = shownState
        // A failed or skipped load keeps the last response, so only the recommendations state reports its results.
        const shownResults = showGroups ? results : []
        const shownGroups = showGroups ? visibleGroups : []
        const directions = new Set(shownResults.filter((row) => row.impact != null).map((row) => row.impactDirection))
        reportRecommendationsShown({
            state: shownState,
            recommendation_count: shownResults.length,
            rule_count: shownGroups.length,
            rules: shownGroups.map((group) => group.rule),
            has_save_impact: directions.has('save'),
            has_gain_impact: directions.has('gain'),
            has_invest_impact: directions.has('invest'),
            source_types: [...new Set(sources.map((source) => source.sourceType))],
            data_gap_count: dataGaps.length,
            dismissed_count: showGroups ? dismissedCount : 0,
            intro_shown: showGroups && !introSeen,
        })
        // One event per state the viewer sees, so reloads and new date ranges with the same state do not add views.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [shownState])

    return (
        <div className="@container flex flex-col gap-3 pt-2" data-attr="marketing-recommendations">
            <Popover
                visible={showGroups && !introSeen}
                placement="bottom-start"
                showArrow
                overlay={
                    <div className="flex max-w-80 flex-col gap-2 p-2">
                        <strong>New: recommendations</strong>
                        <p className="mb-0">
                            Built from your Google Ads and Google Search Console data. They show where to cut wasted
                            spend, where to grow, and which pages to improve for organic search. They are suggestions,
                            so check each one before you edit a campaign.
                        </p>
                        <div className="flex justify-end gap-2">
                            <LemonButton size="small" onClick={dismissIntro}>
                                Got it
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => openFirstRule('intro')}
                                data-attr="marketing-recommendations-intro-open"
                            >
                                See recommendations
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                    {shownState === 'recommendations' ? (
                        <RecommendationsSummary results={results} onOpen={() => openFirstRule('button')} />
                    ) : shownState === null ? (
                        <LemonSkeleton className="h-6 w-60" />
                    ) : (
                        <RecommendationsIdle state={shownState} />
                    )}
                </div>
            </Popover>
            {dataWarehouseSources && sources.length > 0 && responseError ? (
                <MarketingQueryError
                    message="Could not load recommendations. Try again, and contact support if it keeps happening."
                    queryId={queryId}
                    onRetry={() => loadData('force_async')}
                    loading={responseLoading}
                />
            ) : null}
            <RecommendationsModal
                isOpen={selectedRule !== null}
                onClose={closeRecommendations}
                total={results.length}
                totals={sumImpact(results)}
                dismissedCount={dismissedCount}
                sections={sections}
                selectedGroup={selectedGroup}
                onSelect={(group) =>
                    group.rule !== selectedGroup?.rule &&
                    selectRule(group.rule, withoutDismissed(group.recommendations, dismissedKeys).length)
                }
                dataNodeProps={dataNodeProps}
                dataGaps={dataGaps}
                disclaimer={recommendationsResponse?.disclaimer}
            />
        </div>
    )
}
