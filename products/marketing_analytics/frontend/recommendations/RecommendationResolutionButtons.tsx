import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationResolutionButtons({
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
                <LemonTag type={resolution === 'applied' ? 'success' : 'muted'}>
                    {resolution === 'applied' ? 'Applied' : 'Dismissed'}
                </LemonTag>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    loading={loading}
                    tooltip="Show this recommendation again for everyone in this project"
                    onClick={() => restoreRecommendation(recommendation)}
                    aria-label={`Restore ${recommendation.subject}`}
                    data-attr="marketing-recommendations-restore"
                >
                    Restore
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-end gap-0.5 whitespace-nowrap">
            {recommendation.impactDirection !== 'keep' && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    loading={loading}
                    tooltip="Mark that you made this change. It stays hidden for everyone in this project until someone restores it."
                    onClick={() => resolveRecommendation(recommendation, 'applied')}
                    aria-label={`Mark ${recommendation.subject} as applied`}
                    data-attr="marketing-recommendations-mark-applied"
                >
                    Mark as applied
                </LemonButton>
            )}
            <LemonButton
                size="xsmall"
                type="tertiary"
                loading={loading}
                tooltip="Hide this recommendation for everyone in this project, for any date range, until someone restores it."
                onClick={() => resolveRecommendation(recommendation, 'dismissed')}
                aria-label={`Dismiss ${recommendation.subject}`}
                data-attr="marketing-recommendations-dismiss"
            >
                Dismiss
            </LemonButton>
        </div>
    )
}
