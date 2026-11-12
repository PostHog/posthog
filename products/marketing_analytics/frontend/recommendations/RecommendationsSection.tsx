import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconLightBulb } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonButtonProps, LemonSkeleton, Popover, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { RecommendationsShownState } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRecommendationsQueryResponse } from '~/queries/schema/schema-general'

import { MarketingQueryError } from '../dashboard/MarketingQueryError'
import { RecommendationDataGapButton } from './RecommendationDataGapButton'
import {
    IMPACT_DIRECTION_DESCRIPTIONS,
    IMPACT_DIRECTION_LABELS,
    RecommendationTotal,
    groupRecommendations,
    sectionRecommendations,
    sumImpact,
} from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'
import { RecommendationsModal } from './RecommendationsModal'

const IDLE_MESSAGES: Record<RecommendationsShownState, string | null> = {
    recommendations: null,
    no_connected_source: 'Connect Google Ads to get recommendations on budgets, search terms and wasted spend.',
    no_selected_source:
        'Select a Google Ads or Google Search Console source with synced tables to see recommendations.',
    error: null,
    empty: 'No recommendations for this period.',
}

function ImpactSummary({ totals }: { totals: RecommendationTotal[] }): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-secondary">
            {totals.map((total) => (
                <Tooltip
                    key={`${total.direction}-${total.currency}`}
                    title={IMPACT_DIRECTION_DESCRIPTIONS[total.direction]}
                >
                    <span className="cursor-help">
                        {`${IMPACT_DIRECTION_LABELS[total.direction]} `}
                        <span className="font-semibold text-primary" translate="no">
                            {`${formatMarketingMoney(total.amount, total.currency, true)}/mo`}
                        </span>
                    </span>
                </Tooltip>
            ))}
        </span>
    )
}

export function RecommendationsSection(): JSX.Element {
    const {
        dataNodeProps,
        dataWarehouseSources,
        sources,
        hasAdsSource,
        dataGaps,
        selectedRule,
        introSeen,
        connectedSourceTypes,
    } = useValues(recommendationsLogic)
    const {
        openRecommendations,
        selectRule,
        closeRecommendations,
        dismissIntro,
        reportRecommendationsShown,
        reportRecommendationsActionClicked,
    } = useActions(recommendationsLogic)
    const { response, responseLoading, responseError, queryId } = useValues(dataNodeLogic(dataNodeProps))
    const { loadData } = useActions(dataNodeLogic(dataNodeProps))

    const recommendationsResponse = response as MarketingAnalyticsRecommendationsQueryResponse | null
    const results = recommendationsResponse?.results ?? []
    const groups = groupRecommendations(results)
    const sections = sectionRecommendations(groups)
    const firstRule = sections[0]?.groups[0]?.rule
    // Reloading can drop the open rule, so the modal falls back to the first one instead of closing on its own.
    const selectedGroup =
        selectedRule === null
            ? undefined
            : (groups.find((group) => group.rule === selectedRule) ?? sections[0]?.groups[0])
    const sourcesLoading = !dataWarehouseSources
    const connectGoogleAds = (location: 'section_empty' | 'section_campaigns'): LemonButtonProps => ({
        children: 'Connect Google Ads',
        // pinned: entry_point on the source connect events, renaming it splits the attribution
        to: urls.dataWarehouseSourceNew(
            'GoogleAds',
            urls.marketingAnalyticsApp(),
            'Marketing analytics',
            undefined,
            'marketing_analytics_recommendations'
        ),
        'data-attr': 'marketing-recommendations-connect-google-ads',
        sideIcon: null,
        onClick: () => reportRecommendationsActionClicked('connect_google_ads', location),
    })

    const showGroups = sources.length > 0 && !responseError && !!firstRule
    const shownState: RecommendationsShownState | null = showGroups
        ? 'recommendations'
        : sourcesLoading || (responseLoading && sources.length > 0)
          ? null
          : connectedSourceTypes.length === 0
            ? 'no_connected_source'
            : sources.length === 0
              ? 'no_selected_source'
              : responseError
                ? 'error'
                : 'empty'
    const idleMessage = shownState ? IDLE_MESSAGES[shownState] : null
    const idleReason =
        shownState === 'empty'
            ? 'Campaign rules compare active campaigns in the same ad account, so an account with one campaign gets few. Search term rules need synced search term tables, and Google Search Console for the organic ones.'
            : (idleMessage ?? 'Recommendations could not load.')

    const reportedState = useRef<RecommendationsShownState | null>(null)
    useEffect(() => {
        if (!shownState || shownState === reportedState.current) {
            return
        }
        reportedState.current = shownState
        // A failed or skipped load keeps the last response, so only the recommendations state reports its results.
        const shownResults = shownState === 'recommendations' ? results : []
        const directions = new Set(shownResults.filter((row) => row.impact != null).map((row) => row.impactDirection))
        reportRecommendationsShown({
            state: shownState,
            recommendation_count: shownResults.length,
            rule_count: shownState === 'recommendations' ? groups.length : 0,
            rules: shownState === 'recommendations' ? groups.map((group) => group.rule) : [],
            has_save_impact: directions.has('save'),
            has_gain_impact: directions.has('gain'),
            has_invest_impact: directions.has('invest'),
            source_types: [...new Set(sources.map((source) => source.sourceType))],
            data_gap_count: dataGaps.length,
            intro_shown: shownState === 'recommendations' && !introSeen,
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
                                onClick={() => firstRule && openRecommendations(firstRule, 'intro', results.length)}
                                data-attr="marketing-recommendations-intro-open"
                            >
                                See recommendations
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                    {showGroups ? (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconLightBulb />}
                                sideIcon={<LemonBadge.Number count={results.length} maxDigits={3} />}
                                onClick={() => firstRule && openRecommendations(firstRule, 'button', results.length)}
                                data-attr="marketing-recommendations-open"
                            >
                                Recommendations
                            </LemonButton>
                            <ImpactSummary totals={sumImpact(results)} />
                            {dataGaps.length > 0 && (
                                <RecommendationDataGapButton
                                    gaps={dataGaps}
                                    dataAttr="marketing-recommendations-data-gaps"
                                    location="section_data_gaps"
                                />
                            )}
                        </>
                    ) : shownState === null ? (
                        <LemonSkeleton className="h-6 w-60" />
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconLightBulb />}
                                sideIcon={null}
                                disabledReason={idleReason}
                            >
                                Recommendations
                            </LemonButton>
                            {idleMessage && <span className="text-secondary">{idleMessage}</span>}
                            {connectedSourceTypes.length === 0 && (
                                <LemonButton type="secondary" size="small" {...connectGoogleAds('section_empty')} />
                            )}
                        </>
                    )}
                    {showGroups && !hasAdsSource && (
                        <span className="text-secondary">
                            Connect Google Ads and sync its campaign tables to also get campaign recommendations.
                        </span>
                    )}
                    {showGroups && !hasAdsSource && !connectedSourceTypes.includes('GoogleAds') && (
                        <LemonButton type="tertiary" size="small" {...connectGoogleAds('section_campaigns')} />
                    )}
                </div>
            </Popover>
            {!sourcesLoading && sources.length > 0 && responseError ? (
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
                sections={sections}
                selectedGroup={selectedGroup}
                onSelect={(group) =>
                    group.rule !== selectedGroup?.rule && selectRule(group.rule, group.recommendations.length)
                }
                dataNodeProps={dataNodeProps}
                dataGaps={dataGaps}
                disclaimer={recommendationsResponse?.disclaimer}
            />
        </div>
    )
}
