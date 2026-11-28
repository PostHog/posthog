import { useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { QuillRecommendationCountBadge } from './QuillRecommendationCountBadge'
import { QuillRecommendationDataGapButton } from './QuillRecommendationDataGapButton'
import { QuillRecommendationsConnectGoogleAdsButton } from './QuillRecommendationsConnectGoogleAdsButton'
import { IMPACT_DIRECTION_DESCRIPTIONS, IMPACT_DIRECTION_LABELS } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationsSummary({ onOpen }: { onOpen: () => void }): JSX.Element {
    const { hasAdsSource, dataGaps, serverDataGaps, connectedSourceTypes, activeRecommendations, totals } =
        useValues(recommendationsLogic)

    return (
        <>
            <Button variant="outline" onClick={onOpen} data-attr="marketing-recommendations-open">
                <IconLightBulb />
                <span>Recommendations</span>
                <QuillRecommendationCountBadge count={activeRecommendations.length} maxDigits={3} />
            </Button>
            {activeRecommendations.length > 0 ? (
                <Text
                    size="xs"
                    variant="muted"
                    render={<span className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1" />}
                >
                    {totals.map((total) => (
                        <Tooltip key={`${total.direction}-${total.currency}`}>
                            <TooltipTrigger render={<span tabIndex={0} className="cursor-help" />}>
                                <span>{`${IMPACT_DIRECTION_LABELS[total.direction]} `}</span>
                                <span className="font-semibold text-foreground" translate="no">
                                    {`${formatMarketingMoney(total.amount, total.currency, true)}/mo`}
                                </span>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                {IMPACT_DIRECTION_DESCRIPTIONS[total.direction]}
                            </TooltipContent>
                        </Tooltip>
                    ))}
                </Text>
            ) : (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    All recommendations for this period are dismissed or applied.
                </Text>
            )}
            {dataGaps.length + serverDataGaps.length > 0 && (
                <QuillRecommendationDataGapButton
                    gaps={dataGaps}
                    serverGaps={serverDataGaps}
                    dataAttr="marketing-recommendations-data-gaps"
                    location="section_data_gaps"
                />
            )}
            {!hasAdsSource && (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Connect Google Ads and sync its campaign tables to also get campaign recommendations.
                </Text>
            )}
            {!hasAdsSource && !connectedSourceTypes.includes('GoogleAds') && (
                <QuillRecommendationsConnectGoogleAdsButton type="tertiary" location="section_campaigns" />
            )}
        </>
    )
}
