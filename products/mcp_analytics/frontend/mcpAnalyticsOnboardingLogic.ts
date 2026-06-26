import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import type { mcpAnalyticsOnboardingLogicType } from './mcpAnalyticsOnboardingLogicType'

export type MCPOnboardingState = 'not-instrumented' | 'connected-no-calls' | 'onboarded'

export interface MCPOnboardingSignals {
    /** A client has completed the MCP handshake — proves the SDK wrap is live. */
    hasInitialize: boolean
    /** A tool has actually been called — the server is in use. */
    hasToolCall: boolean
}

// Two-signal funnel over all history. `$mcp_initialize` fires when an agent
// connects (before any tool call), so it distinguishes "instrumented but no
// traffic yet" from "not instrumented at all" — without it, a freshly-wired
// server that hasn't been called looks identical to one that was never set up.
// Filtering on the two event names hits the events sort key, so this stays cheap.
const ONBOARDING_SIGNAL_QUERY = `
SELECT
    countIf(event = '$mcp_initialize') > 0 AS has_initialize,
    countIf(event = '$mcp_tool_call') > 0 AS has_tool_call
FROM events
WHERE event IN ('$mcp_initialize', '$mcp_tool_call')
`

// While the user is still onboarding we re-check on a timer so the page flips to
// the dashboard on its own the moment the first events land. The disposables
// plugin pauses this on hidden tabs and tears it down on unmount.
const POLL_INTERVAL_MS = 20000

export const mcpAnalyticsOnboardingLogic = kea<mcpAnalyticsOnboardingLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsOnboardingLogic']),
    loaders({
        signals: {
            __default: null as MCPOnboardingSignals | null,
            loadSignals: async (_: void, breakpoint): Promise<MCPOnboardingSignals> => {
                const response = (await api.query({
                    kind: NodeKind.HogQLQuery,
                    query: ONBOARDING_SIGNAL_QUERY,
                })) as HogQLQueryResponse
                breakpoint()
                const row = (response?.results?.[0] as unknown[] | undefined) ?? []
                return { hasInitialize: Boolean(row[0]), hasToolCall: Boolean(row[1]) }
            },
        },
    }),
    selectors({
        onboardingState: [
            (s) => [s.signals],
            (signals): MCPOnboardingState | null => {
                if (!signals) {
                    return null
                }
                if (signals.hasToolCall) {
                    return 'onboarded'
                }
                if (signals.hasInitialize) {
                    return 'connected-no-calls'
                }
                return 'not-instrumented'
            },
        ],
        isOnboarded: [(s) => [s.onboardingState], (onboardingState): boolean => onboardingState === 'onboarded'],
    }),
    listeners(({ values, cache }) => ({
        loadSignalsSuccess: () => {
            // Once tool calls show up the gate flips for good — stop polling.
            if (values.isOnboarded) {
                cache.disposables.dispose('poll')
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadSignals()
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.loadSignals(), POLL_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'poll')
    }),
])
