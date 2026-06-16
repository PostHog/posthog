import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { HogFunctionSubTemplateIdType } from '~/types'

import type { recommendationsTabLogicType } from './recommendationsTabLogicType'
import type {
    AlertsRecommendation,
    ErrorTrackingRecommendation,
    LongRunningIssuesRecommendation,
    RateLimitsRecommendation,
    SourceMapsRecommendation,
} from './types'

export const isAlertsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is AlertsRecommendation => recommendation.type === 'alerts'

export const isLongRunningIssuesRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is LongRunningIssuesRecommendation => recommendation.type === 'long_running_issues'

export const isRateLimitsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is RateLimitsRecommendation => recommendation.type === 'rate_limits'

export const isSourceMapsRecommendation = (
    recommendation: ErrorTrackingRecommendation
): recommendation is SourceMapsRecommendation => recommendation.type === 'source_maps'

const POLL_INTERVAL_MS = 500

// The backend `status` field is the single source of truth for "is this recommendation
// being computed". The frontend shows a spinner whenever status === 'computing', and
// optimistically flips status to 'computing' before issuing a refresh HTTP call so the
// spinner appears instantly (without waiting for the roundtrip). The optimistic value
// converges with the server response since both arrive at status='computing'.
export const recommendationsTabLogic = kea<recommendationsTabLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'logic']),

    actions({
        loadRecommendations: true,
        pollRecommendations: true,
        refreshRecommendation: (id: string) => ({ id }),
        dismissRecommendation: (id: string) => ({ id }),
        restoreRecommendation: (id: string) => ({ id }),
        suppressIssue: (issueId: string) => ({ issueId }),
        activateIssue: (issueId: string) => ({ issueId }),

        setRecommendations: (recommendations: ErrorTrackingRecommendation[]) => ({ recommendations }),
        upsertRecommendation: (recommendation: ErrorTrackingRecommendation) => ({ recommendation }),
        markRecommendationComputing: (id: string) => ({ id }),
        setRecommendationsLoading: (loading: boolean) => ({ loading }),

        ensurePollingScheduled: true,
        clearPolling: true,

        toggleDismissedExpanded: true,
        toggleCompletedExpanded: true,
        setOpenAlertTriggerKey: (triggerKey: HogFunctionSubTemplateIdType | null) => ({ triggerKey }),
    }),

    reducers({
        recommendations: [
            [] as ErrorTrackingRecommendation[],
            {
                setRecommendations: (_, { recommendations }) => recommendations,
                upsertRecommendation: (state, { recommendation }) =>
                    state.map((r) => (r.id === recommendation.id ? recommendation : r)),
                markRecommendationComputing: (state, { id }) =>
                    state.map((r) => (r.id === id ? { ...r, status: 'computing' as const } : r)),
            },
        ],
        recommendationsLoading: [
            true,
            {
                setRecommendationsLoading: (_, { loading }) => loading,
            },
        ],
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

    listeners(({ actions, values, cache }) => ({
        loadRecommendations: async () => {
            actions.setRecommendationsLoading(true)
            try {
                const response = await api.errorTracking.listRecommendations()
                actions.setRecommendations(response.results)
            } finally {
                actions.setRecommendationsLoading(false)
            }
        },
        pollRecommendations: async () => {
            try {
                const response = await api.errorTracking.listRecommendations({ poll: true })
                actions.setRecommendations(response.results)
            } catch {
                actions.ensurePollingScheduled()
            }
        },
        refreshRecommendation: async ({ id }) => {
            // Optimistic flip — the spinner appears instantly. The server response will
            // confirm the same status, so there's no flicker when it arrives.
            actions.markRecommendationComputing(id)
            try {
                const updated = await api.errorTracking.refreshRecommendation(id)
                actions.upsertRecommendation(updated)
            } catch {
                lemonToast.error('Failed to refresh recommendation')
                // Polling will reconcile state regardless of which side errored.
            }
        },
        dismissRecommendation: async ({ id }) => {
            const updated = await api.errorTracking.dismissRecommendation(id)
            actions.upsertRecommendation(updated)
        },
        restoreRecommendation: async ({ id }) => {
            const updated = await api.errorTracking.restoreRecommendation(id)
            actions.upsertRecommendation(updated)
        },
        suppressIssue: async ({ issueId }) => {
            await api.errorTracking.updateIssue(issueId, { status: 'suppressed' })
            const longRunning = values.recommendations.find(isLongRunningIssuesRecommendation)
            if (!longRunning) {
                return
            }
            // force=false: just re-pulls enriched meta, no recompute. So we don't mark computing.
            const updated = await api.errorTracking.refreshRecommendation(longRunning.id, { force: false })
            actions.upsertRecommendation(updated)
        },
        activateIssue: async ({ issueId }) => {
            await api.errorTracking.updateIssue(issueId, { status: 'active' })
            const longRunning = values.recommendations.find(isLongRunningIssuesRecommendation)
            if (!longRunning) {
                return
            }
            const updated = await api.errorTracking.refreshRecommendation(longRunning.id, { force: false })
            actions.upsertRecommendation(updated)
        },

        // Polling lifecycle: any time the recommendations state changes, re-evaluate
        // whether we still need to poll. Schedule one timer at a time.
        setRecommendations: () => actions.ensurePollingScheduled(),
        upsertRecommendation: () => actions.ensurePollingScheduled(),
        markRecommendationComputing: () => actions.ensurePollingScheduled(),
        ensurePollingScheduled: () => {
            const stillComputing = values.recommendations.some((r) => r.status === 'computing')
            if (!stillComputing) {
                actions.clearPolling()
                return
            }
            if (cache.pollTimeoutId !== undefined) {
                return
            }
            cache.pollTimeoutId = window.setTimeout(() => {
                cache.pollTimeoutId = undefined
                actions.pollRecommendations()
            }, POLL_INTERVAL_MS)
        },
        clearPolling: () => {
            if (cache.pollTimeoutId !== undefined) {
                window.clearTimeout(cache.pollTimeoutId)
                cache.pollTimeoutId = undefined
            }
        },
    })),

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
        computingIds: [
            (s) => [s.recommendations],
            (recommendations): Set<string> =>
                new Set(recommendations.filter((r) => r.status === 'computing').map((r) => r.id)),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRecommendations()
    }),

    beforeUnmount(({ actions }) => {
        actions.clearPolling()
    }),
])
