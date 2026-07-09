import { afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { retryWithBackoff } from 'lib/utils/async'
import { teamLogic } from 'scenes/teamLogic'

import { metricsHasMetricsRetrieve } from './generated/api'
import type { metricsIngestionLogicType } from './metricsIngestionLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const metricsIngestionLogic = kea<metricsIngestionLogicType>([
    path(['products', 'metrics', 'frontend', 'metricsIngestionLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ values }) => ({
        teamHasMetrics: {
            __default: undefined as boolean | undefined,
            loadTeamHasMetrics: async (): Promise<boolean> => {
                const response = await retryWithBackoff(() => metricsHasMetricsRetrieve(String(values.currentTeamId)), {
                    maxAttempts: 3,
                })
                return Boolean(response.hasMetrics)
            },
        },
    })),

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
