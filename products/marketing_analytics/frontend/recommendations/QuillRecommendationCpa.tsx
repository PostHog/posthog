import { IconInfo } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationCpaSummary } from './RecommendationCpa'

export function QuillRecommendationCpa({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element | null {
    const summary = recommendationCpaSummary(recommendation)
    if (!summary) {
        return null
    }
    return (
        <Text size="xs" variant="muted" render={<span className="m-0 flex flex-wrap items-center gap-x-2" />}>
            {summary.cpa !== null && (
                <span className="tabular-nums" translate="no">
                    {summary.cpa}
                </span>
            )}
            <span className="inline-flex items-center gap-1">
                <span>
                    <span className="tabular-nums" translate="no">
                        {summary.benchmark}
                    </span>
                    <span>{summary.source}</span>
                </span>
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About the benchmark" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{summary.tooltip}</TooltipContent>
                </Tooltip>
            </span>
        </Text>
    )
}
