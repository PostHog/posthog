import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { WeeklyDigestRecommendation } from './types'

export function WeeklyDigestRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: WeeklyDigestRecommendation
    dismissed?: boolean
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { updateUser, updateETWeeklyDigestForTeam } = useActions(userLogic)
    const { refreshRecommendation } = useActions(recommendationsTabLogic)

    const enabled = recommendation.meta.enabled

    const handleEnable = (): void => {
        if (!user?.notification_settings || !currentTeamId) {
            return
        }
        posthog.capture('error_tracking_weekly_digest_enabled_from_recommendation')

        // Flip the ET-specific toggle on if needed, then opt this project in.
        // We deliberately don't touch `all_weekly_digest_disabled` — that's a
        // global preference the user set elsewhere and isn't ours to override.
        if (user.notification_settings.error_tracking_weekly_digest === false) {
            updateUser({
                notification_settings: {
                    ...user.notification_settings,
                    error_tracking_weekly_digest: true,
                },
            })
        }
        updateETWeeklyDigestForTeam(currentTeamId, true)
        refreshRecommendation(recommendation.id)
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            nextRefreshAt={recommendation.next_refresh_at}
            title="Weekly digest"
            description={
                <>
                    Every Monday we'll email you a summary of top issues, new regressions, and crash-free session rate
                    for this project. See{' '}
                    <Link to={urls.settings('user-notifications', 'notifications')}>notifications settings</Link>.
                </>
            }
            dismissed={dismissed}
            progress={enabled ? { current: 1, total: 1, label: 'subscribed' } : undefined}
        >
            {!enabled && (
                <LemonButton size="small" type="primary" onClick={handleEnable}>
                    Send it to me
                </LemonButton>
            )}
        </RecommendationCard>
    )
}
