import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type {
    CrossSellRecommendationRun,
    ErrorTrackingRecommendationRun,
    ErrorTrackingRecommendationSettingsResponse,
    ErrorTrackingRecommendationType,
} from './types'

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
        settings: [
            null as ErrorTrackingRecommendationSettingsResponse | null,
            {
                loadSettings: async () => {
                    return await api.errorTracking.getRecommendationSettings()
                },
                dismissRecommendation: async (type: ErrorTrackingRecommendationType) => {
                    const current = await api.errorTracking.getRecommendationSettings()
                    const ignored = new Set(current.ignored_recommendation_types)
                    ignored.add(type)
                    return await api.errorTracking.updateRecommendationSettings({
                        ignored_recommendation_types: Array.from(ignored),
                    })
                },
                restoreRecommendation: async (type: ErrorTrackingRecommendationType) => {
                    const current = await api.errorTracking.getRecommendationSettings()
                    const ignored = new Set(current.ignored_recommendation_types)
                    ignored.delete(type)
                    return await api.errorTracking.updateRecommendationSettings({
                        ignored_recommendation_types: Array.from(ignored),
                    })
                },
            },
        ],
    }),

    selectors({
        activeRecommendations: [
            (s) => [s.recommendations, s.settings],
            (recommendations, settings): ErrorTrackingRecommendationRun[] => {
                const ignored = new Set(settings?.ignored_recommendation_types ?? [])
                return recommendations.filter((r) => !ignored.has(r.type))
            },
        ],
        ignoredRecommendations: [
            (s) => [s.recommendations, s.settings],
            (recommendations, settings): ErrorTrackingRecommendationRun[] => {
                const ignored = new Set(settings?.ignored_recommendation_types ?? [])
                return recommendations.filter((r) => ignored.has(r.type))
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRecommendations()
        actions.loadSettings()
    }),
])

export const isCrossSellRecommendation = (
    recommendation: ErrorTrackingRecommendationRun
): recommendation is CrossSellRecommendationRun => recommendation.type === 'cross_sell'
