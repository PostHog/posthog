import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { IMPACT_DIRECTION_DESCRIPTIONS, IMPACT_DIRECTION_LABELS, RecommendationTotal } from './recommendations'

export const QUILL_DIRECTION_BADGE: Record<
    MarketingAnalyticsRecommendation['impactDirection'],
    'success' | 'info' | 'warning' | 'default'
> = {
    save: 'success',
    gain: 'info',
    invest: 'warning',
    keep: 'default',
}

export function QuillRecommendationImpactTotals({ totals }: { totals: RecommendationTotal[] }): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-1">
            {totals.map((total) => (
                <Tooltip key={`${total.direction}-${total.currency}`}>
                    <TooltipTrigger render={<span tabIndex={0} className="inline-flex" />}>
                        <Badge variant={QUILL_DIRECTION_BADGE[total.direction]}>
                            <span translate="no">
                                {`${IMPACT_DIRECTION_LABELS[total.direction]} ${formatMarketingMoney(total.amount, total.currency, true)}/mo`}
                            </span>
                        </Badge>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">
                        {IMPACT_DIRECTION_DESCRIPTIONS[total.direction]}
                    </TooltipContent>
                </Tooltip>
            ))}
        </span>
    )
}
