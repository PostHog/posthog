import { useActions, useValues } from 'kea'

import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { DETECTED_CHANGE_DESCRIPTIONS } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationResolutionButtons({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element {
    const { pendingKeys } = useValues(recommendationsLogic)
    const { resolveRecommendation, restoreRecommendation } = useActions(recommendationsLogic)
    const resolution = recommendation.resolution?.resolution
    const loading = pendingKeys.includes(recommendation.key)

    if (resolution) {
        return (
            <div className="flex items-center justify-end gap-1 whitespace-nowrap">
                <Badge variant={resolution === 'applied' ? 'success' : 'default'}>
                    {resolution === 'applied' ? 'Applied' : 'Dismissed'}
                </Badge>
                <Button
                    size="sm"
                    loading={loading}
                    tooltip="Show this recommendation again for everyone in this project"
                    onClick={() => restoreRecommendation(recommendation)}
                    aria-label={`Restore ${recommendation.subject}`}
                    data-attr="marketing-recommendations-restore"
                >
                    Restore
                </Button>
            </div>
        )
    }

    if (recommendation.detectedChange) {
        return (
            <div className="flex items-center justify-end whitespace-nowrap">
                <Tooltip>
                    <TooltipTrigger render={<span tabIndex={0} className="inline-flex" />}>
                        <Badge variant="success">Applied</Badge>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">
                        {DETECTED_CHANGE_DESCRIPTIONS[recommendation.detectedChange]}
                    </TooltipContent>
                </Tooltip>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-end gap-0.5 whitespace-nowrap">
            {recommendation.impactDirection !== 'keep' && (
                <Button
                    size="sm"
                    loading={loading}
                    tooltip="Mark that you made this change. It stays hidden for everyone in this project until someone restores it."
                    onClick={() => resolveRecommendation(recommendation, 'applied')}
                    aria-label={`Mark ${recommendation.subject} as applied`}
                    data-attr="marketing-recommendations-mark-applied"
                >
                    Mark as applied
                </Button>
            )}
            <Button
                size="sm"
                loading={loading}
                tooltip="Hide this recommendation for everyone in this project, for any date range, until someone restores it."
                onClick={() => resolveRecommendation(recommendation, 'dismissed')}
                aria-label={`Dismiss ${recommendation.subject}`}
                data-attr="marketing-recommendations-dismiss"
            >
                Dismiss
            </Button>
        </div>
    )
}
