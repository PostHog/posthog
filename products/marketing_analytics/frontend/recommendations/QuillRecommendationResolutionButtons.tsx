import { useActions, useValues } from 'kea'

import { Badge, Button, cn, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { DETECTED_CHANGE_DESCRIPTIONS } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationResolutionButtons({
    recommendation,
    stacked = false,
}: {
    recommendation: MarketingAnalyticsRecommendation
    stacked?: boolean
}): JSX.Element {
    const { pendingKeys } = useValues(recommendationsLogic)
    const { resolveRecommendation, restoreRecommendation } = useActions(recommendationsLogic)
    const resolution = recommendation.resolution?.resolution
    const loading = pendingKeys.includes(recommendation.key)

    if (resolution) {
        return (
            <div className={cn('flex flex-wrap items-center gap-1 whitespace-nowrap', !stacked && 'justify-end')}>
                <Badge variant={resolution === 'applied' ? 'success' : 'default'}>
                    {resolution === 'applied' ? 'Applied' : 'Dismissed'}
                </Badge>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={loading}
                    aria-busy={loading || undefined}
                    tooltip="Show this recommendation again for everyone in this project"
                    onClick={() => restoreRecommendation(recommendation)}
                    aria-label={`Restore ${recommendation.subject}`}
                    data-attr="marketing-recommendations-restore"
                >
                    <span>Restore</span>
                    {loading && <Spinner />}
                </Button>
            </div>
        )
    }

    if (recommendation.detectedChange) {
        return (
            <div className={cn('flex items-center whitespace-nowrap', !stacked && 'justify-end')}>
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
        <div
            className={cn(
                'flex gap-1 whitespace-nowrap',
                stacked ? 'flex-row flex-wrap items-center' : 'flex-col items-end'
            )}
        >
            {recommendation.impactDirection !== 'keep' && (
                <Button
                    variant="outline"
                    size="sm"
                    disabled={loading}
                    aria-busy={loading || undefined}
                    tooltip="Mark that you made this change. It stays hidden for everyone in this project until someone restores it."
                    onClick={() => resolveRecommendation(recommendation, 'applied')}
                    aria-label={`Mark ${recommendation.subject} as applied`}
                    data-attr="marketing-recommendations-mark-applied"
                >
                    <span>Mark as applied</span>
                    {loading && <Spinner />}
                </Button>
            )}
            <Button
                variant="outline"
                size="sm"
                disabled={loading}
                aria-busy={loading || undefined}
                tooltip="Hide this recommendation for everyone in this project, for any date range, until someone restores it."
                onClick={() => resolveRecommendation(recommendation, 'dismissed')}
                aria-label={`Dismiss ${recommendation.subject}`}
                data-attr="marketing-recommendations-dismiss"
            >
                <span>Dismiss</span>
                {loading && <Spinner />}
            </Button>
        </div>
    )
}
