import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { RecommendationCpaValues } from './RecommendationCpaValues'
import { BENCHMARK_SOURCE_DESCRIPTIONS, BENCHMARK_SOURCE_LABELS } from './recommendations'

export interface RecommendationCpaSummary {
    cpa: string | null
    benchmark: string
    source: string
    tooltip: string
}

export function recommendationCpaSummary(
    recommendation: MarketingAnalyticsRecommendation
): RecommendationCpaSummary | null {
    const { cpa, currency } = recommendation
    if (!cpa || cpa.benchmark == null || !cpa.benchmarkSource) {
        return null
    }
    const money = (amount: number): string => formatMarketingMoney(amount, currency)
    const range =
        cpa.bestCampaign != null && cpa.worstCampaign != null && cpa.bestCampaign !== cpa.worstCampaign
            ? ` Non-brand CPA across your non-brand Search campaigns ranges from ${money(cpa.bestCampaign)} to ${money(cpa.worstCampaign)}.`
            : ''
    return {
        cpa: cpa.value != null ? `CPA ${money(cpa.value)}` : null,
        benchmark: `Benchmark ${money(cpa.benchmark)}`,
        source: `, ${BENCHMARK_SOURCE_LABELS[cpa.benchmarkSource]}`,
        tooltip: `${BENCHMARK_SOURCE_DESCRIPTIONS[cpa.benchmarkSource]}${range}`,
    }
}

export function RecommendationCpa({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element | null {
    const summary = recommendationCpaSummary(recommendation)
    if (!summary) {
        return null
    }
    return (
        <span className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
            <RecommendationCpaValues
                summary={summary}
                info={
                    <Tooltip title={summary.tooltip}>
                        <IconInfo className="shrink-0 text-sm" />
                    </Tooltip>
                }
            />
        </span>
    )
}
