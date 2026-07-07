import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import type { debugLogsLogicType } from './debugLogsLogicType'

/**
 * Staff-only preference for whether `_posthog/console` debug rows surface in the run thread. Persisted
 * to localStorage and shared across every run surface (singleton, unkeyed), enabled by default. An
 * impersonated session always forces debug logs on, independent of the persisted toggle, so an engineer
 * debugging a customer's session never has them silently hidden.
 */
export const debugLogsLogic = kea<debugLogsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'debugLogsLogic']),
    connect(() => ({
        values: [userLogic, ['user'], preflightLogic, ['isDev']],
    })),
    actions({
        setDebugLogsEnabled: (enabled: boolean) => ({ enabled }),
    }),
    reducers({
        debugLogsEnabled: [
            true,
            { persist: true, storageKey: 'posthog_ai.debugLogsEnabled' },
            {
                setDebugLogsEnabled: (_, { enabled }) => enabled,
            },
        ],
    }),
    selectors({
        /** Who may see and toggle debug logs at all: staff or local dev. Impersonation force-shows them. */
        canControlDebugLogs: [
            (s) => [s.user, s.isDev],
            (user, isDev): boolean => !!user?.is_staff || !!isDev,
        ],
        /**
         * Whether debug rows should actually render. Impersonation always shows them; otherwise staff/dev
         * see them subject to the persisted toggle (on by default); everyone else never does.
         */
        showDebugLogs: [
            (s) => [s.user, s.canControlDebugLogs, s.debugLogsEnabled],
            (user, canControlDebugLogs, debugLogsEnabled): boolean =>
                !!user?.is_impersonated || (canControlDebugLogs && debugLogsEnabled),
        ],
    }),
])
