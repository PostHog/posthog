import { IconInfo } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationCpaBenchmarkTooltip } from './RecommendationCpa'
import { BENCHMARK_SOURCE_LABELS } from './recommendations'

export function QuillRecommendationCpa({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element | null {
    const { cpa, currency } = recommendation
    const tooltip = recommendationCpaBenchmarkTooltip(recommendation)
    if (!cpa || cpa.benchmark == null || !cpa.benchmarkSource || tooltip === null) {
        return null
    }
    const money = (amount: number): string => formatMarketingMoney(amount, currency)
    return (
        <Text size="xs" variant="muted" render={<span className="m-0 flex flex-wrap items-center gap-x-2" />}>
            {cpa.value != null && <span className="tabular-nums" translate="no">{`CPA ${money(cpa.value)}`}</span>}
            <span className="inline-flex items-center gap-1">
                <span>
                    <span className="tabular-nums" translate="no">{`Benchmark ${money(cpa.benchmark)}`}</span>
                    <span>{`, ${BENCHMARK_SOURCE_LABELS[cpa.benchmarkSource]}`}</span>
                </span>
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About the benchmark" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
                </Tooltip>
            </span>
        </Text>
    )
}
