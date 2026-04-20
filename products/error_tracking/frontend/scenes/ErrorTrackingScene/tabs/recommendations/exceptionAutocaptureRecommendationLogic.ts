import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { exceptionAutocaptureRecommendationLogicType } from './exceptionAutocaptureRecommendationLogicType'
import { recommendationsTabLogic } from './recommendationsTabLogic'

export const exceptionAutocaptureRecommendationLogic = kea<exceptionAutocaptureRecommendationLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingScene',
        'tabs',
        'recommendations',
        'exceptionAutocapture',
    ]),

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
            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam) {
                return
            }
            posthog.capture('error_tracking_recommendation_exception_autocapture_enabled')
            teamLogic.actions.addProductIntent({
                product_type: ProductKey.ERROR_TRACKING,
                intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
            })
            actions.setEnableInProgress(true)
            try {
                await teamLogic.asyncActions.updateCurrentTeam({ autocapture_exceptions_opt_in: true })
                eventUsageLogic.actions.reportAutocaptureExceptionsToggled(true)
                recommendationsTabLogic.actions.refreshRecommendation(recommendationId)
            } finally {
                actions.setEnableInProgress(false)
            }
        },
    })),
])
