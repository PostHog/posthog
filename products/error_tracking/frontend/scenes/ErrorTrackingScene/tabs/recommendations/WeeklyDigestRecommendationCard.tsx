import { useActions, useAsyncActions, useValues } from 'kea'
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
    const { updateUser } = useAsyncActions(userLogic)
    const { enableInProgressId } = useValues(recommendationsTabLogic)
    const { refreshRecommendation, setEnableInProgress } = useActions(recommendationsTabLogic)

    const enabled = recommendation.meta.enabled
    const isLoading = enableInProgressId === recommendation.id

    const handleEnable = async (): Promise<void> => {
        if (!user?.notification_settings || !currentTeamId) {
            return
        }
        posthog.capture('error_tracking_weekly_digest_enabled_from_recommendation')

        // Flip the ET-specific toggle on AND opt this project in, in one request.
        // Doing it as two sequential `updateUser` calls (e.g. via `updateETWeeklyDigestForTeam`)
        // races on the server — both requests read stale state on the client and send the
        // full `notification_settings` object, so whichever arrives last overwrites the other
        // and `error_tracking_weekly_digest` can get reset to `false`.
        // We deliberately don't touch `all_weekly_digest_disabled` — that's a global preference
        // the user set elsewhere and isn't ours to override.
        setEnableInProgress(recommendation.id)
        try {
            await updateUser({
                notification_settings: {
                    ...user.notification_settings,
                    error_tracking_weekly_digest: true,
                    error_tracking_weekly_digest_project_enabled: {
                        ...user.notification_settings.error_tracking_weekly_digest_project_enabled,
                        [currentTeamId]: true,
                    },
                },
            })
            refreshRecommendation(recommendation.id)
        } finally {
            setEnableInProgress(null)
        }
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
                <LemonButton size="small" type="secondary" onClick={handleEnable} loading={isLoading}>
                    Subscribe me
                </LemonButton>
            )}
        </RecommendationCard>
    )
}
