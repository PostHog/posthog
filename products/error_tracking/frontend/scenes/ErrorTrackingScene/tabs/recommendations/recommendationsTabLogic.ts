import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type { AlertsRecommendation, ErrorTrackingRecommendation, LongRunningIssuesRecommendation } from './types'

export const isAlertsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is AlertsRecommendation => recommendation.type === 'alerts'

export const isLongRunningIssuesRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is LongRunningIssuesRecommendation => recommendation.type === 'long_running_issues'

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
                    } catch (error) {
                        lemonToast.error('Failed to refresh recommendation')
                        throw error
                    } finally {
                        actions.setRecommendationRefreshing(id, false)
                    }
                },
                suppressIssue: async ({ issueId }: { issueId: string }) => {
                    await api.errorTracking.updateIssue(issueId, { status: 'suppressed' })
                    const longRunning = values.recommendations.find(isLongRunningIssuesRecommendation)
                    if (!longRunning) {
                        return values.recommendations
                    }
                    const updated = await api.errorTracking.refreshRecommendation(longRunning.id, { force: false })
                    return values.recommendations.map((r) => (r.id === updated.id ? updated : r))
                },
                activateIssue: async ({ issueId }: { issueId: string }) => {
                    await api.errorTracking.updateIssue(issueId, { status: 'active' })
                    const longRunning = values.recommendations.find(isLongRunningIssuesRecommendation)
                    if (!longRunning) {
                        return values.recommendations
                    }
                    const updated = await api.errorTracking.refreshRecommendation(longRunning.id, { force: false })
                    return values.recommendations.map((r) => (r.id === updated.id ? updated : r))
                },
            },
        ],
    })),

    actions({
        toggleDismissedExpanded: true,
        toggleCompletedExpanded: true,
        setOpenAlertTriggerKey: (triggerKey: HogFunctionSubTemplateIdType | null) => ({ triggerKey }),
        setRecommendationRefreshing: (id: string, refreshing: boolean) => ({ id, refreshing }),
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
        refreshingIds: [
            new Set<string>(),
            {
                setRecommendationRefreshing: (state, { id, refreshing }) => {
                    const next = new Set(state)
                    if (refreshing) {
                        next.add(id)
                    } else {
                        next.delete(id)
                    }
                    return next
                },
            },
        ],
    }),

    selectors({
        activeRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !r.dismissed_at && !r.completed)
            },
        ],
        completedRecommendations: [
            (s) => [s.recommendations],
            (recommendations): ErrorTrackingRecommendation[] => {
                return recommendations.filter((r) => !r.dismissed_at && r.completed)
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
