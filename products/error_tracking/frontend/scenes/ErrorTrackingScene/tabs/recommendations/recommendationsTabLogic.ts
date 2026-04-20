import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type {
    AlertsRecommendation,
    CrossSellRecommendation,
    ErrorTrackingRecommendation,
    ExceptionAutocaptureRecommendation,
    WeeklyDigestRecommendation,
} from './types'

export const recommendationsTabLogic = kea<recommendationsTabLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'logic']),

    connect(() => ({
        actions: [userLogic, ['updateUserSuccess'], teamLogic, ['updateCurrentTeamSuccess']],
    })),

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
        // Queue a refresh for this recommendation to fire as soon as the next
        // `updateUserSuccess` / `updateCurrentTeamSuccess` lands. Without waiting for the
        // update to persist, refreshing immediately would re-read stale state and the
        // recommendation meta would bounce back to "not enabled" until the next auto-refresh.
        scheduleRefreshOnUpdate: (id: string) => ({ id }),
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
        pendingRefreshRecommendationId: [
            null as string | null,
            {
                scheduleRefreshOnUpdate: (_, { id }) => id,
                refreshRecommendationSuccess: () => null,
                refreshRecommendationFailure: () => null,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        updateUserSuccess: () => {
            if (values.pendingRefreshRecommendationId) {
                actions.refreshRecommendation(values.pendingRefreshRecommendationId)
            }
        },
        updateCurrentTeamSuccess: () => {
            if (values.pendingRefreshRecommendationId) {
                actions.refreshRecommendation(values.pendingRefreshRecommendationId)
            }
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
