import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { RecommendationCard } from './RecommendationCard'
import type { WeeklyDigestRecommendation } from './types'
import { weeklyDigestRecommendationLogic } from './weeklyDigestRecommendationLogic'

// Deep-link straight to the ET weekly digest section inside the user notifications settings
// page. `UpdateEmailPreferences` reads `?highlight=...` and scrolls + rings the matching block.
const ET_WEEKLY_DIGEST_SETTINGS_URL = combineUrl('/settings/user-notifications', { highlight: 'et-weekly-digest' }).url

export function WeeklyDigestRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: WeeklyDigestRecommendation
    dismissed?: boolean
}): JSX.Element {
    const { enableInProgress } = useValues(weeklyDigestRecommendationLogic)
    const { enable } = useActions(weeklyDigestRecommendationLogic)

    const enabled = recommendation.meta.enabled

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            nextRefreshAt={recommendation.next_refresh_at}
            title="Weekly digest"
            description={
                <>
                    Every Monday we'll email you a summary of top issues, new regressions, and crash-free session rate
                    for this project. See <Link to={ET_WEEKLY_DIGEST_SETTINGS_URL}>notifications settings</Link>.
                </>
            }
            dismissed={dismissed}
            progress={enabled ? { current: 1, total: 1, label: 'subscribed' } : undefined}
        >
            {!enabled && (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => enable(recommendation.id)}
                    loading={enableInProgress}
                >
                    Subscribe me
                </LemonButton>
            )}
        </RecommendationCard>
    )
}
