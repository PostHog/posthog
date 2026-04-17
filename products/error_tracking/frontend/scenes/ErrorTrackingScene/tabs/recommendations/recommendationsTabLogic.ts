import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type { CrossSellRecommendation, ErrorTrackingRecommendation } from './types'

export const recommendationsTabLogic = kea<recommendationsTabLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'logic']),

    loaders({
        recommendations: [
            [] as ErrorTrackingRecommendation[],
            {
                loadRecommendations: async () => {
                    const response = await api.errorTracking.listRecommendations()
                    return response.results
                },
                dismissRecommendation: async (id: string) => {
                    await api.errorTracking.dismissRecommendation(id)
                    const response = await api.errorTracking.listRecommendations()
                    return response.results
                },
                restoreRecommendation: async (id: string) => {
                    await api.errorTracking.restoreRecommendation(id)
                    const response = await api.errorTracking.listRecommendations()
                    return response.results
                },
                refreshRecommendation: async (id: string) => {
                    await api.errorTracking.refreshRecommendation(id)
                    const response = await api.errorTracking.listRecommendations()
                    return response.results
                },
            },
        ],
    }),

    actions({
        toggleDismissedExpanded: true,
    }),

    reducers({
        dismissedExpanded: [
            false,
            {
                toggleDismissedExpanded: (state) => !state,
            },
        ],
    }),

    selectors({
        activeRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !r.dismissed_at)
            },
        ],
        ignoredRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !!r.dismissed_at)
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRecommendations()
    }),
])

export const isCrossSellRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is CrossSellRecommendation => recommendation.type === 'cross_sell'
