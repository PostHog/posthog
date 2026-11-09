import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { recommendationKey } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationDismissButton({
    recommendation,
}: {
    recommendation: MarketingAnalyticsRecommendation
}): JSX.Element {
    const { dismissedKeys, pendingKeys } = useValues(recommendationsLogic)
    const { dismissRecommendation, restoreRecommendation } = useActions(recommendationsLogic)
    const key = recommendationKey(recommendation)
    const loading = pendingKeys.includes(key)

    return dismissedKeys.has(key) ? (
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
    ) : (
        <LemonButton
            size="xsmall"
            type="tertiary"
            loading={loading}
            tooltip="Hide this recommendation for everyone in this project, for any date range, until someone restores it."
            onClick={() => dismissRecommendation(recommendation)}
            data-attr="marketing-recommendations-dismiss"
        >
            Dismiss
        </LemonButton>
    )
}
