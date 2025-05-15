import { actions, kea, path, reducers } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { loaders } from 'node_modules/kea-loaders/lib'

import type { logsLogicType } from './logsLogicType'
import { LogMessage } from './types'

const LOG_MESSAGE: LogMessage = {
    uuid: uuid(),
    team_id: 1,
    trace_id: uuid(),
    span_id: uuid(),
    body: 'This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge. This is a messagge',
    attributes: { stream: '12345', boom: 'lolool' },
    timestamp: '2025-05-14T21:39:26Z',
    observed_timestamp: '2025-05-14T21:39:26Z',
    severity_text: 'debug',
    resource: 'cymbal',
}

export const DEFAULT_LOGS: LogMessage[] = [
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
    LOG_MESSAGE,
]

export const logsLogic = kea<logsLogicType>([
    path(['products', 'logs', 'frontend', 'logsLogic']),

    actions({
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
    }),

    reducers({
        logs: [DEFAULT_LOGS],
        wrapBody: [
            true as boolean,
            {
                setWrapBody: (_, { wrapBody }) => wrapBody,
            },
        ],
    }),

    loaders({
        logs: {
            __default: undefined as boolean | undefined,
            fetchLogs: async (): Promise<boolean> => {
                const response = await api.logs.query({ query: {} })
                debugger
                return response
            },
        },
    }),
])
