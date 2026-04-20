import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type {
    AlertsRecommendation,
    CrossSellRecommendation,
    ErrorTrackingRecommendation,
    ErrorTrackingRecommendationType,
    ExceptionAutocaptureRecommendation,
    WeeklyDigestRecommendation,
} from './types'

export type RecommendationInteractionType = 'click'

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
        toggleCompletedExpanded: true,
        setOpenAlertTriggerKey: (triggerKey: HogFunctionSubTemplateIdType | null) => ({ triggerKey }),
        recordRecommendationInteraction: (
            recommendationType: ErrorTrackingRecommendationType,
            interactionType: RecommendationInteractionType
        ) => ({ recommendationType, interactionType }),
    }),

    reducers({
        dismissedExpanded: [
            false,
            {
                toggleDismissedExpanded: (state) => !state,
            },
        ],
        completedExpanded: [
            false,
            {
                toggleCompletedExpanded: (state) => !state,
            },
        ],
        openAlertTriggerKey: [
            null as HogFunctionSubTemplateIdType | null,
            {
                setOpenAlertTriggerKey: (_, { triggerKey }) => triggerKey,
            },
        ],
    }),

    listeners(({ values }) => ({
        recordRecommendationInteraction: ({ recommendationType, interactionType }) => {
            posthog.capture('error_tracking_recommendation_interacted', {
                recommendation_type: recommendationType,
                interaction_type: interactionType,
            })
        },
        dismissRecommendation: (id) => {
            const rec = values.recommendations.find((r) => r.id === id)
            posthog.capture('error_tracking_recommendation_dismissed', {
                recommendation_type: rec?.type ?? null,
            })
        },
        restoreRecommendation: (id) => {
            const rec = values.recommendations.find((r) => r.id === id)
            posthog.capture('error_tracking_recommendation_restored', {
                recommendation_type: rec?.type ?? null,
            })
        },
    })),

    selectors({
        pendingRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !r.dismissed_at && (r.completion_progress ?? 0) < 1)
            },
        ],
        completedRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !r.dismissed_at && (r.completion_progress ?? 0) >= 1)
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

export const isAlertsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is AlertsRecommendation => recommendation.type === 'alerts'

export const isWeeklyDigestRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is WeeklyDigestRecommendation => recommendation.type === 'weekly_digest'

export const isExceptionAutocaptureRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is ExceptionAutocaptureRecommendation => recommendation.type === 'exception_autocapture'
