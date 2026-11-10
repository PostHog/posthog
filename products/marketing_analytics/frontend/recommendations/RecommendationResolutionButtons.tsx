import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationKey } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationResolutionButtons({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element {
    const { pendingKeys } = useValues(recommendationsLogic)
    const { resolveRecommendation, restoreRecommendation } = useActions(recommendationsLogic)
    const resolution = recommendation.resolution?.state
    const loading = pendingKeys.includes(recommendationKey(recommendation))

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
                    data-attr="marketing-recommendations-restore"
                >
                    Restore
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex items-center justify-end gap-1 whitespace-nowrap">
            <LemonButton
                size="xsmall"
                type="tertiary"
                loading={loading}
                tooltip="Mark that you made this change. It stays hidden for everyone in this project until someone restores it."
                onClick={() => resolveRecommendation(recommendation, 'applied')}
                data-attr="marketing-recommendations-mark-applied"
            >
                Mark as applied
            </LemonButton>
            <LemonButton
                size="xsmall"
                type="tertiary"
                loading={loading}
                tooltip="Hide this recommendation for everyone in this project, for any date range, until someone restores it."
                onClick={() => resolveRecommendation(recommendation, 'dismissed')}
                data-attr="marketing-recommendations-dismiss"
            >
                Dismiss
            </LemonButton>
        </div>
    )
}
