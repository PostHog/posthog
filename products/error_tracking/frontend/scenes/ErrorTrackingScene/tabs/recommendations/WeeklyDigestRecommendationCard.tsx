import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
}): JSX.Element | null {
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
            description="Every Monday we'll email you a summary of top issues, new regressions, and crash-free session rate for this project."
            dismissed={dismissed}
        >
            {enabled ? (
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-success text-sm">
                        <IconCheckCircle className="text-base" />
                        <span className="font-medium">You're subscribed</span>
                    </div>
                    <LemonButton size="small" type="tertiary" to={urls.settings('user-notifications', 'notifications')}>
                        Manage in settings
                    </LemonButton>
                </div>
            ) : (
                <div className="flex items-center gap-2">
                    <LemonButton size="small" type="primary" onClick={handleEnable}>
                        Send it to me
                    </LemonButton>
                    <LemonButton size="small" type="tertiary" to={urls.settings('user-notifications', 'notifications')}>
                        Manage in settings
                    </LemonButton>
                </div>
            )}
        </RecommendationCard>
    )
}
