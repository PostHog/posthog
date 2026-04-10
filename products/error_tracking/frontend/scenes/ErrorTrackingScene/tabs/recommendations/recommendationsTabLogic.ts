import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type { CrossSellRecommendationRun, ErrorTrackingRecommendationRun } from './types'

export const recommendationsTabLogic = kea<recommendationsTabLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'logic']),

    loaders({
        recommendations: [
            [] as ErrorTrackingRecommendationRun[],
            {
                loadRecommendations: async () => {
                    const response = await api.errorTracking.listRecommendations()
                    return response.results
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRecommendations()
    }),
])

export const isCrossSellRecommendation = (
    recommendation: ErrorTrackingRecommendationRun
): recommendation is CrossSellRecommendationRun => recommendation.type === 'cross_sell'
