import { actions, kea, path, reducers } from 'kea'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { logDetailsModalLogicType } from './logDetailsModalLogicType'

export const logDetailsModalLogic = kea<logDetailsModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogDetailsModal', 'logDetailsModalLogic']),

    actions({
        openLogDetails: (log: ParsedLogMessage) => ({ log }),
        closeLogDetails: true,
        setJsonParseAllFields: (enabled: boolean) => ({ enabled }),
    }),

    reducers({
        selectedLog: [
            null as ParsedLogMessage | null,
            {
                openLogDetails: (_, { log }) => log,
                closeLogDetails: () => null,
            },
        ],
        isOpen: [
            false,
            {
                openLogDetails: () => true,
                closeLogDetails: () => false,
            },
        ],
        jsonParseAllFields: [
            false,
            {
                setJsonParseAllFields: (_, { enabled }) => enabled,
            },
        ],
    }),
])
