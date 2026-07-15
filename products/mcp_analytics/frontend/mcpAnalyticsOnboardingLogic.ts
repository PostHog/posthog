import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'

import { HogQLQueryResponse, NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { mcpAnalyticsOnboardingLogicType } from './mcpAnalyticsOnboardingLogicType'
import { asNumber } from './queryResultParsers'

export type MCPOnboardingState = 'not-instrumented' | 'connected-no-calls' | 'onboarded'

/**
 * Which question the dashboard answers, by volume. `activity` is for "what are
 * agents doing with my server?" — a live feed, verbatim intents, and an
 * instrumentation checklist; windowed metrics would be noise at this volume.
 * `metrics` is the standard dashboard for "is it healthy?". Volume-gated rather
 * than time-gated so a low-traffic server never regresses to an empty dashboard.
 */
export type MCPDashboardStage = 'activity' | 'metrics'

/** Metrics and trends unlock on lifetime volume… */
export const METRICS_UNLOCK_LIFETIME_CALLS = 300
/** …or on sustained density, whichever comes first. */
export const METRICS_UNLOCK_7D_CALLS = 250

export interface MCPOnboardingSignals {
    /** A client has completed the MCP handshake — proves the SDK wrap is live. */
    hasInitialize: boolean
    /** A tool has actually been called — the server is in use. */
    hasToolCall: boolean
    /** Lifetime `$mcp_tool_call` count — drives the activity/metrics stage gate. */
    toolCallsTotal: number
    /** `$mcp_tool_call` count over the last 7 days — the density half of the gate. */
    toolCalls7d: number
    /** Timestamp of the first tool call, for "since June 30" copy. Null before the first call. */
    firstCallAt: string | null
}

// Signal funnel over all history. `$mcp_initialize` fires when an agent connects
// (before any tool call), so it distinguishes "instrumented but no traffic yet"
// from "not instrumented at all". Counts (not booleans) so the same query drives
// the activity/metrics stage gate. Deliberately no `properties.*` access: event-name +
// timestamp filters hit the events sort key, so this stays cheap even on projects
// with millions of MCP events — property-derived stats live in mcpEarlyDataLogic,
// whose queries are time-bounded.
const ONBOARDING_SIGNAL_QUERY = `
SELECT
    countIf(event = '$mcp_initialize') > 0 AS has_initialize,
    countIf(event = '$mcp_tool_call') AS tool_calls_total,
    countIf(event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 7 DAY) AS tool_calls_7d,
    minIf(timestamp, event = '$mcp_tool_call') AS first_call_at
FROM events
WHERE event IN ('$mcp_initialize', '$mcp_tool_call')
`

// While the user is onboarding (or watching the activity stage fill in) we re-check
// on a timer so the page advances on its own as events land. The disposables plugin
// pauses this on hidden tabs and tears it down on unmount.
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
                // moment. Forcing keeps the flip near-instant. Polling stops once the project
                // graduates to the full dashboard (see loadSignalsSuccess), so this is bounded
                // to the onboarding + activity window, and the query itself is cheap (event-name
                // counts on the sort key).
                const response = (await api.query(
                    {
                        kind: NodeKind.HogQLQuery,
                        query: ONBOARDING_SIGNAL_QUERY,
                    },
                    { refresh: 'force_blocking' }
                )) as HogQLQueryResponse
                breakpoint()
                const row = (response?.results?.[0] as unknown[] | undefined) ?? []
                const toolCallsTotal = asNumber(row[1])
                return {
                    hasInitialize: asNumber(row[0]) > 0,
                    hasToolCall: toolCallsTotal > 0,
                    toolCallsTotal,
                    toolCalls7d: asNumber(row[2]),
                    // minIf() returns the epoch sentinel when nothing matched — only trust it
                    // once we know at least one call exists.
                    firstCallAt: toolCallsTotal > 0 && typeof row[3] === 'string' ? row[3] : null,
                }
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
        dashboardStage: [
            (s) => [s.signals],
            (signals): MCPDashboardStage | null => {
                if (!signals || !signals.hasToolCall) {
                    return null
                }
                return signals.toolCallsTotal >= METRICS_UNLOCK_LIFETIME_CALLS ||
                    signals.toolCalls7d >= METRICS_UNLOCK_7D_CALLS
                    ? 'metrics'
                    : 'activity'
            },
        ],
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
            // Keep polling through the activity stage so the summary advances live;
            // stop for good once the volume gate graduates the project to metrics.
            if (values.dashboardStage === 'metrics') {
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
