import { actions, kea, listeners, path, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { logDetailsModalLogicType } from './logDetailsModalLogicType'

export type LogDetailsTab = 'details' | 'explore-ai' | 'comments'

export const logDetailsModalLogic = kea<logDetailsModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogDetailsModal', 'logDetailsModalLogic']),

    actions({
        openLogDetails: (log: ParsedLogMessage) => ({ log }),
        closeLogDetails: true,
        setJsonParseAllFields: (enabled: boolean) => ({ enabled }),
        setActiveTab: (tab: LogDetailsTab) => ({ tab }),
    }),

    listeners(() => ({
        setActiveTab: ({ tab }) => {
            posthog.capture('logs details tab changed', { tab })
        },
    })),

    subscriptions(() => ({
        isOpen: (isOpen: boolean, previousIsOpen: boolean) => {
            if (isOpen && !previousIsOpen) {
                posthog.capture('logs details opened')
            }
        },
    })),

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
        activeTab: [
            'details' as LogDetailsTab,
            {
                setActiveTab: (_, { tab }) => tab,
                openLogDetails: () => 'details',
                closeLogDetails: () => 'details',
            },
        ],
    }),
])
