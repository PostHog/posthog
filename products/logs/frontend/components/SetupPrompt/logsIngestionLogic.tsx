import { afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { retryWithBackoff } from 'lib/utils'

import type { logsIngestionLogicType } from './logsIngestionLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const logsIngestionLogic = kea<logsIngestionLogicType>([
    path(['products', 'logs', 'components', 'SetupPrompt', 'logsIngestionLogic']),
    loaders({
        teamHasLogs: {
            __default: undefined as boolean | undefined,
            loadTeamHasLogs: async (): Promise<boolean> => {
                return await retryWithBackoff(() => api.logs.hasLogs(), { maxAttempts: 3 })
            },
        },
    }),

    reducers({
        teamHasLogsCheckFailed: [
            false,
            {
                loadTeamHasLogs: () => false,
                loadTeamHasLogsSuccess: () => false,
                loadTeamHasLogsFailure: () => true,
            },
        ],
        cachedTeamHasLogs: [
            null as boolean | null,
            { persist: true, prefix: `${teamId}__` },
            {
                // Only cache true - logs don't disappear once ingested
                loadTeamHasLogsSuccess: (_, { teamHasLogs }) => teamHasLogs || null,
            },
        ],
    }),

    selectors({
        hasLogs: [
            (s) => [s.teamHasLogs, s.cachedTeamHasLogs],
            (teamHasLogs, cachedTeamHasLogs): boolean | undefined => teamHasLogs ?? cachedTeamHasLogs ?? undefined,
        ],
    }),

    afterMount(({ actions, values }) => {
        if (values.cachedTeamHasLogs !== true) {
            actions.loadTeamHasLogs()
        }
    }),
])
