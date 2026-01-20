import { afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { retryWithBackoff } from 'lib/utils'

import type { logsIngestionLogicType } from './logsIngestionLogicType'

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
    }),

    afterMount(({ actions }) => {
        actions.loadTeamHasLogs()
    }),
])
