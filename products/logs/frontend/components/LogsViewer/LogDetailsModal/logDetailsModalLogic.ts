import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { ParsedLogMessage } from 'products/logs/frontend/types'
import { isSessionIdKey } from 'products/logs/frontend/utils'

import type { logDetailsModalLogicType } from './logDetailsModalLogicType'

export type LogDetailsTab = 'details' | 'raw' | 'explore-ai' | 'comments' | 'related-errors'

export interface LogDetailsModalProps {
    tabId: string
}

export const logDetailsModalLogic = kea<logDetailsModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogDetailsModal', 'logDetailsModalLogic']),
    props({} as LogDetailsModalProps),
    key((props) => props.tabId),

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
        isLogDetailsOpen: (isLogDetailsOpen: boolean, wasOpen: boolean) => {
            if (isLogDetailsOpen && !wasOpen) {
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
        isLogDetailsOpen: [
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

    selectors({
        sessionId: [
            (s) => [s.selectedLog],
            (selectedLog): string | null => {
                if (!selectedLog) {
                    return null
                }

                // Check log attributes first
                for (const [key, value] of Object.entries(selectedLog?.attributes || {})) {
                    if (isSessionIdKey(key) && value) {
                        return String(value)
                    }
                }

                // Then check resource_attributes
                for (const [key, value] of Object.entries(selectedLog?.resource_attributes || {})) {
                    if (isSessionIdKey(key) && value) {
                        return String(value)
                    }
                }

                return null
            },
        ],
        hasSessionId: [(s) => [s.sessionId], (sessionId): boolean => sessionId !== null],
    }),
])
