import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'

import { HogQLQueryResponse, NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { mcpAnalyticsOnboardingLogicType } from './mcpAnalyticsOnboardingLogicType'

export type MCPOnboardingState = 'not-instrumented' | 'connected-no-calls' | 'onboarded'

/**
 * How much data the project has, once onboarded. `early` mixes progressive
 * small-data sections into the dashboard; `full` is the standard windowed
 * dashboard. Volume-gated rather than time-gated so a low-traffic server never
 * regresses to an empty dashboard.
 */
export type MCPDataMaturity = 'early' | 'full'

/**
 * The dashboard's information hierarchy, by volume. `warming` leads with the
 * live feed (metrics would be noise); `emerging` adds the windowed key metrics
 * and charts on top; `mature` is the standard dashboard with the early
 * sections retired.
 */
export type MCPDashboardStage = 'warming' | 'emerging' | 'mature'

/** Windowed key metrics and charts appear once trends are meaningful. */
export const KEY_METRICS_LIFETIME_CALLS = 300
/** The early sections retire on lifetime volume… */
export const FULL_DASHBOARD_LIFETIME_CALLS = 1000
/** …or on sustained density, whichever comes first. */
export const FULL_DASHBOARD_7D_CALLS = 250

export interface MCPOnboardingSignals {
    /** A client has completed the MCP handshake — proves the SDK wrap is live. */
    hasInitialize: boolean
    /** A tool has actually been called — the server is in use. */
    hasToolCall: boolean
    /** Lifetime `$mcp_tool_call` count — drives the early/full maturity gate. */
    toolCallsTotal: number
    /** `$mcp_tool_call` count over the last 7 days — the density half of the gate. */
    toolCalls7d: number
    /** Timestamp of the first tool call, for "since June 30" copy. Null before the first call. */
    firstCallAt: string | null
}

// Signal funnel over all history. `$mcp_initialize` fires when an agent connects
// (before any tool call), so it distinguishes "instrumented but no traffic yet"
// from "not instrumented at all". Counts (not booleans) so the same query drives
// the early/full maturity gate. Deliberately no `properties.*` access: event-name +
// timestamp filters hit the events sort key, so this stays cheap even on projects
// with millions of MCP events — property-derived stats live in mcpEarlyDataLogic,
// which only mounts when volume is known to be small.
const ONBOARDING_SIGNAL_QUERY = `
SELECT
    countIf(event = '$mcp_initialize') > 0 AS has_initialize,
    countIf(event = '$mcp_tool_call') AS tool_calls_total,
    countIf(event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 7 DAY) AS tool_calls_7d,
    minIf(timestamp, event = '$mcp_tool_call') AS first_call_at
FROM events
WHERE event IN ('$mcp_initialize', '$mcp_tool_call')
`

// While the user is onboarding (or watching the early-data view fill in) we re-check
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
                // to the onboarding + early-data window, and the query itself is cheap (event-name
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
                // ClickHouse returns booleans as 0/1 and counts possibly stringified; coerce
                // numerically so a stringified "0" can never read as truthy.
                const asNumber = (value: unknown): number => Number(value) || 0
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
        dataMaturity: [
            (s) => [s.signals],
            (signals): MCPDataMaturity | null => {
                if (!signals || !signals.hasToolCall) {
                    return null
                }
                return signals.toolCallsTotal >= FULL_DASHBOARD_LIFETIME_CALLS ||
                    signals.toolCalls7d >= FULL_DASHBOARD_7D_CALLS
                    ? 'full'
                    : 'early'
            },
        ],
        dashboardStage: [
            (s) => [s.signals, s.dataMaturity],
            (signals, dataMaturity): MCPDashboardStage | null => {
                if (!dataMaturity) {
                    return null
                }
                if (dataMaturity === 'full') {
                    return 'mature'
                }
                return (signals?.toolCallsTotal ?? 0) >= KEY_METRICS_LIFETIME_CALLS ? 'emerging' : 'warming'
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
            // Keep polling through the early-data window so the progress header and
            // milestones advance live; stop for good once the volume gate graduates
            // the project to the full dashboard.
            if (values.dataMaturity === 'full') {
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
