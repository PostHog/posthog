import { afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { retryWithBackoff } from 'lib/utils/async'

import type { metricsIngestionLogicType } from './metricsIngestionLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const metricsIngestionLogic = kea<metricsIngestionLogicType>([
    path(['products', 'metrics', 'frontend', 'metricsIngestionLogic']),
    loaders({
        teamHasMetrics: {
            __default: undefined as boolean | undefined,
            loadTeamHasMetrics: async (): Promise<boolean> => {
                return await retryWithBackoff(() => api.metrics.hasMetrics(), { maxAttempts: 3 })
            },
        },
    }),

    reducers({
        teamHasMetricsCheckFailed: [
            false,
            {
                loadTeamHasMetrics: () => false,
                loadTeamHasMetricsSuccess: () => false,
                loadTeamHasMetricsFailure: () => true,
            },
        ],
        cachedTeamHasMetrics: [
            null as boolean | null,
            { persist: true, prefix: `${teamId}__` },
            {
                // Only cache true - metrics don't disappear once ingested
                loadTeamHasMetricsSuccess: (_, { teamHasMetrics }) => teamHasMetrics || null,
            },
        ],
    }),

    selectors({
        hasMetrics: [
            (s) => [s.teamHasMetrics, s.cachedTeamHasMetrics],
            (teamHasMetrics, cachedTeamHasMetrics): boolean | undefined =>
                teamHasMetrics ?? cachedTeamHasMetrics ?? undefined,
        ],
    }),

    afterMount(({ actions, values }) => {
        if (values.cachedTeamHasMetrics !== true) {
            actions.loadTeamHasMetrics()
        }
    }),
])
