import { useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import { LemonBadge, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { RecommendationDataGapButton } from './RecommendationDataGapButton'
import { IMPACT_DIRECTION_DESCRIPTIONS, IMPACT_DIRECTION_LABELS, RecommendationTotal } from './recommendations'
import { RecommendationsConnectGoogleAdsButton } from './RecommendationsConnectGoogleAdsButton'
import { recommendationsLogic } from './recommendationsLogic'

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

export function RecommendationsSummary({ onOpen }: { onOpen: () => void }): JSX.Element {
    const { hasAdsSource, dataGaps, connectedSourceTypes, activeRecommendations, totals } =
        useValues(recommendationsLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconLightBulb />}
                sideIcon={<LemonBadge.Number count={activeRecommendations.length} maxDigits={3} />}
                onClick={onOpen}
                data-attr="marketing-recommendations-open"
            >
                Recommendations
            </LemonButton>
            {activeRecommendations.length > 0 ? (
                <ImpactSummary totals={totals} />
            ) : (
                <span className="text-secondary">All recommendations for this period are dismissed or applied.</span>
            )}
            {dataGaps.length > 0 && (
                <RecommendationDataGapButton
                    gaps={dataGaps}
                    dataAttr="marketing-recommendations-data-gaps"
                    location="section_data_gaps"
                />
            )}
            {!hasAdsSource && (
                <span className="text-secondary">
                    Connect Google Ads and sync its campaign tables to also get campaign recommendations.
                </span>
            )}
            {!hasAdsSource && !connectedSourceTypes.includes('GoogleAds') && (
                <RecommendationsConnectGoogleAdsButton type="tertiary" location="section_campaigns" />
            )}
        </>
    )
}
