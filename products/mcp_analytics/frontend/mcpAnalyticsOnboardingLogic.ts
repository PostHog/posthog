import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'

import { HogQLQueryResponse, NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

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
                // Force a fresh calculation instead of reading a cached result. The first
                // events on a new project land a beat after capture returns 200, so a poll
                // during that gap caches `[0,0]` — and with the default cache TTL the page
                // would then keep serving that stale "not onboarded" answer for up to a
                // minute after the data is actually queryable, dulling the "you're connected!"
                // moment. Forcing keeps the flip near-instant. Polling stops as soon as we're
                // onboarded (see loadSignalsSuccess), so this is bounded to the onboarding
                // window, and the query itself is cheap (two event-name counts on the sort key).
                const response = (await api.query(
                    {
                        kind: NodeKind.HogQLQuery,
                        query: ONBOARDING_SIGNAL_QUERY,
                    },
                    { refresh: 'force_blocking' }
                )) as HogQLQueryResponse
                breakpoint()
                const row = (response?.results?.[0] as unknown[] | undefined) ?? []
                // ClickHouse returns the `> 0` comparisons as 0/1; coerce numerically so a
                // stringified "0" can never read as truthy (Boolean("0") would).
                const truthy = (value: unknown): boolean => Number(value) > 0
                return { hasInitialize: truthy(row[0]), hasToolCall: truthy(row[1]) }
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
            // Mark the diagnostic middle of the funnel: the SDK is connected but no
            // tool calls have landed yet. Separates an install problem (never
            // instrumented) from a traffic problem (wired up, but the server isn't
            // being called). Registered once per mount so the poll doesn't repeat it.
            if (values.onboardingState === 'connected-no-calls' && !cache.registeredConnected) {
                cache.registeredConnected = true
                void addProductIntent({
                    product_type: ProductKey.MCP_ANALYTICS,
                    intent_context: ProductIntentContext.MCP_ANALYTICS_CONNECTED,
                })
            }
            // Once tool calls show up the gate flips for good — stop polling.
            if (values.isOnboarded) {
                cache.disposables.dispose('poll')
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadSignals()
        // Register product intent so activation lands in the standard cross-customer
        // funnel (`has_activated_mcp_analytics` flips once tool calls arrive too).
        void addProductIntent({
            product_type: ProductKey.MCP_ANALYTICS,
            intent_context: ProductIntentContext.MCP_ANALYTICS_VIEWED,
        })
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.loadSignals(), POLL_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'poll')
    }),
])
