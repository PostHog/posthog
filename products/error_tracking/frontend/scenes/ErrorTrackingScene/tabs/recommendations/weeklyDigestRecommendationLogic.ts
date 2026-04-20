import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { weeklyDigestRecommendationLogicType } from './weeklyDigestRecommendationLogicType'

export const weeklyDigestRecommendationLogic = kea<weeklyDigestRecommendationLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'weeklyDigest']),

    actions({
        enable: (recommendationId: string) => ({ recommendationId }),
        setEnableInProgress: (inProgress: boolean) => ({ inProgress }),
    }),

    reducers({
        enableInProgress: [
            false,
            {
                setEnableInProgress: (_, { inProgress }) => inProgress,
            },
        ],
    }),

    listeners(({ actions }) => ({
        enable: async ({ recommendationId }) => {
            const user = userLogic.values.user
            const currentTeamId = teamLogic.values.currentTeamId
            if (!user?.notification_settings || !currentTeamId) {
                return
            }
            posthog.capture('error_tracking_recommendation_weekly_digest_opted_in')

            actions.setEnableInProgress(true)
            try {
                await userLogic.asyncActions.updateUser({
                    notification_settings: {
                        ...user.notification_settings,
                        error_tracking_weekly_digest: true,
                        error_tracking_weekly_digest_project_enabled: {
                            ...user.notification_settings.error_tracking_weekly_digest_project_enabled,
                            [currentTeamId]: true,
                        },
                    },
                })
                recommendationsTabLogic.actions.refreshRecommendation(recommendationId)
            } finally {
                actions.setEnableInProgress(false)
            }
        },
    })),
])
