import { afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { retryWithBackoff } from 'lib/utils/async'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { metricsHasMetricsRetrieve } from './generated/api'
import type { metricsIngestionLogicType } from './metricsIngestionLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const metricsIngestionLogic = kea<metricsIngestionLogicType>([
    path(['products', 'metrics', 'frontend', 'metricsIngestionLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [teamLogic, ['addProductIntent']],
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

    listeners(({ actions, cache }) => ({
        loadTeamHasMetricsSuccess: ({ teamHasMetrics }) => {
            if (!teamHasMetrics) {
                cache.sawNoMetrics = true
                return
            }
            // Only an observed no-metrics -> has-metrics transition is an intent: the user
            // completed external OTel setup during this session. A team whose first check
            // already returns true (or was cached true) just has pre-existing metrics.
            if (cache.sawNoMetrics && !cache.firstIngestIntentFired) {
                cache.firstIngestIntentFired = true
                actions.addProductIntent({
                    product_type: ProductKey.METRICS,
                    intent_context: ProductIntentContext.METRICS_FIRST_INGESTED,
                })
            }
        },
    })),

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
