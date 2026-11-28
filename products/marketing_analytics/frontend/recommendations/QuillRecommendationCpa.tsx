import { IconInfo } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationCpaSummary } from './RecommendationCpa'
import { RecommendationCpaValues } from './RecommendationCpaValues'

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
            <RecommendationCpaValues
                summary={summary}
                info={
                    <Tooltip>
                        <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About the benchmark" />}>
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">{summary.tooltip}</TooltipContent>
                    </Tooltip>
                }
            />
        </Text>
    )
}
