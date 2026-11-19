import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonSkeleton, Popover } from '@posthog/lemon-ui'

import { RecommendationsShownState } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { MarketingQueryError } from '../dashboard/MarketingQueryError'
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
        introSeen,
        responseLoading,
        responseError,
        queryId,
        activeRecommendations,
        activeGroups,
        resolvedCount,
        firstRule,
        shownState,
    } = useValues(recommendationsLogic)
    const { openRecommendations, dismissIntro, reportRecommendationsShown, loadData } = useActions(recommendationsLogic)
    // Hands the current query to the node, which runs it again when the sources or dates change.
    useMountedLogic(dataNodeLogic(dataNodeProps))

    const showGroups = shownState === 'recommendations'
    const openFirstRule = (source: 'intro' | 'button'): void => {
        if (firstRule) {
            openRecommendations(firstRule, source, activeRecommendations.length)
        }
    }

    const reportedState = useRef<RecommendationsShownState | null>(null)
    useEffect(() => {
        if (!shownState || shownState === reportedState.current) {
            return
        }
        reportedState.current = shownState
        // A failed or skipped load keeps the last response, so only the recommendations state reports its results.
        const shownResults = showGroups ? activeRecommendations : []
        const shownGroups = showGroups ? activeGroups : []
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
            resolved_count: showGroups ? resolvedCount : 0,
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
                        <RecommendationsSummary onOpen={() => openFirstRule('button')} />
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
            <RecommendationsModal />
        </div>
    )
}
