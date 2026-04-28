import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type { AlertsRecommendation, ErrorTrackingRecommendation, LongRunningIssuesRecommendation } from './types'

export const recommendationsTabLogic = kea<recommendationsTabLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'logic']),

    loaders(({ values, actions }) => ({
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
                    actions.setRecommendationRefreshing(id, true)
                    try {
                        const updated = await api.errorTracking.refreshRecommendation(id)
                        return values.recommendations.map((r) => (r.id === updated.id ? updated : r))
                    } finally {
                        actions.setRecommendationRefreshing(id, false)
                    }
                },
            },
        ],
    })),

    actions({
        toggleDismissedExpanded: true,
        setOpenAlertTriggerKey: (triggerKey: HogFunctionSubTemplateIdType | null) => ({ triggerKey }),
        suppressIssue: (issueId: string) => ({ issueId }),
        setRecommendationRefreshing: (id: string, refreshing: boolean) => ({ id, refreshing }),
    }),

    reducers({
        dismissedExpanded: [
            false,
            {
                toggleDismissedExpanded: (state) => !state,
            },
        ],
        openAlertTriggerKey: [
            null as HogFunctionSubTemplateIdType | null,
            {
                setOpenAlertTriggerKey: (_, { triggerKey }) => triggerKey,
            },
        ],
        refreshingIds: [
            [] as string[],
            {
                setRecommendationRefreshing: (state, { id, refreshing }) => {
                    if (refreshing) {
                        return state.includes(id) ? state : [...state, id]
                    }
                    return state.filter((i) => i !== id)
                },
            },
        ],
    }),

    listeners(({ actions }) => ({
        suppressIssue: async ({ issueId }) => {
            await api.errorTracking.updateIssue(issueId, { status: 'suppressed' })
            actions.loadRecommendations()
        },
    })),

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

export const isAlertsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is AlertsRecommendation => recommendation.type === 'alerts'

export const isLongRunningIssuesRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is LongRunningIssuesRecommendation => recommendation.type === 'long_running_issues'
