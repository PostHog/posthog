import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { logsIngestionLogicType } from './logsIngestionLogicType'

export const logsIngestionLogic = kea<logsIngestionLogicType>([
    path(['products', 'logs', 'components', 'SetupPrompt', 'logsIngestionLogic']),
    loaders({
        hasLogs: {
            __default: undefined as boolean | undefined,
            loadHasLogs: async (): Promise<boolean> => {
                return await api.logs.hasLogs()
            },
        },
    }),

    afterMount(({ actions }) => {
        actions.loadHasLogs()
    }),
])
