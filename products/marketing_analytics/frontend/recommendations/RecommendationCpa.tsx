import { Tooltip } from '@posthog/lemon-ui'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { BENCHMARK_SOURCE_DESCRIPTIONS, BENCHMARK_SOURCE_LABELS } from './recommendations'

export function RecommendationCpa({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element | null {
    const { cpa, currency } = recommendation
    if (!cpa || cpa.benchmark == null || !cpa.benchmarkSource) {
        return null
    }
    const money = (amount: number): string => formatMarketingMoney(amount, currency)
    const range =
        cpa.bestCampaign != null && cpa.worstCampaign != null && cpa.bestCampaign !== cpa.worstCampaign
            ? ` Non-brand CPA across your non-brand Search campaigns ranges from ${money(cpa.bestCampaign)} to ${money(cpa.worstCampaign)}.`
            : ''
    return (
        <span className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
            {cpa.value != null && <span className="tabular-nums" translate="no">{`CPA ${money(cpa.value)}`}</span>}
            <Tooltip title={`${BENCHMARK_SOURCE_DESCRIPTIONS[cpa.benchmarkSource]}${range}`}>
                <span className="cursor-help underline decoration-dotted underline-offset-2">
                    <span className="tabular-nums" translate="no">{`Benchmark ${money(cpa.benchmark)}`}</span>
                    <span>{`, ${BENCHMARK_SOURCE_LABELS[cpa.benchmarkSource]}`}</span>
                </span>
            </Tooltip>
        </span>
    )
}
