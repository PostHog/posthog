import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { mcpAnalyticsSessionsIntentDigest } from '../generated/api'
import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { asNumber, asOptionalString } from '../queryResultParsers'
import { buildActivitySummary } from './activitySummary'
import { ChecklistItem, EarlyStats, buildChecklist } from './earlyDataChecklist'
import type { mcpEarlyDataLogicType } from './mcpEarlyDataLogicType'

export type { ChecklistItem, EarlyStats } from './earlyDataChecklist'

export interface EarlyRecentCall {
    timestamp: string
    tool: string
    intent: string | null
    isError: boolean
    /** Short human-readable error extracted from the tool's response, when the call failed. */
    errorMessage: string | null
    durationMs: number | null
    clientName: string | null
}

export interface IntentTheme {
    intent: string
    count: number
}

export interface IntentDigest {
    digest: string | null
    intentCount: number
}

export interface EarlyToolRow {
    tool: string
    calls: number
    errors: number
}

export interface EarlyClientRow {
    client: string
    calls: number
}

const EMPTY_STATS: EarlyStats = {
    totalCalls: 0,
    distinctTools: 0,
    distinctSessions: 0,
    distinctClients: 0,
    callsWithIntent: 0,
    errorCalls: 0,
    missingCapabilityReports: 0,
}

// These queries read `properties.*`, which decompresses the properties column for every
// matching row. The activity tab is reachable at any volume, so every aggregate is
// bounded to 90 days — effectively all-time for the low-volume servers the tab is for,
// and a hard cap on the scan for high-volume projects that open it.
const ACTIVITY_WINDOW_SQL = 'timestamp >= now() - INTERVAL 90 DAY'

const EARLY_STATS_QUERY = `
SELECT
    countIf(event = '$mcp_tool_call') AS total_calls,
    uniqIf(properties.$mcp_tool_name, event = '$mcp_tool_call') AS distinct_tools,
    uniqIf(properties.$session_id, event = '$mcp_tool_call') AS distinct_sessions,
    uniqIf(properties.$mcp_client_name, event = '$mcp_tool_call' AND properties.$mcp_client_name IS NOT NULL AND properties.$mcp_client_name != '') AS distinct_clients,
    countIf(event = '$mcp_tool_call' AND properties.$mcp_intent IS NOT NULL AND properties.$mcp_intent != '') AS calls_with_intent,
    countIf(event = '$mcp_tool_call' AND toString(properties.$mcp_is_error) IN ('true', '1')) AS error_calls,
    countIf(event = '$mcp_missing_capability') AS missing_capability_reports
FROM events
WHERE event IN ('$mcp_tool_call', '$mcp_missing_capability') AND ${ACTIVITY_WINDOW_SQL}
`

const TOP_TOOLS_QUERY = `
SELECT
    properties.$mcp_tool_name AS tool,
    count() AS calls,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors
FROM events
WHERE event = '$mcp_tool_call' AND properties.$mcp_tool_name IS NOT NULL AND ${ACTIVITY_WINDOW_SQL}
GROUP BY tool
ORDER BY calls DESC
LIMIT 5
`

const CLIENTS_QUERY = `
SELECT
    properties.$mcp_client_name AS client,
    count() AS calls
FROM events
WHERE event = '$mcp_tool_call' AND ${ACTIVITY_WINDOW_SQL}
GROUP BY client
ORDER BY calls DESC
LIMIT 6
`

const RECENT_CALLS_QUERY = `
SELECT
    timestamp,
    properties.$mcp_tool_name AS tool,
    properties.$mcp_intent AS intent,
    toString(properties.$mcp_is_error) IN ('true', '1') AS is_error,
    if(toString(properties.$mcp_is_error) IN ('true', '1'), toString(properties.$mcp_response), NULL) AS error_response,
    toFloat(properties.$mcp_duration_ms) AS duration_ms,
    properties.$mcp_client_name AS client_name
FROM events
WHERE event = '$mcp_tool_call' AND ${ACTIVITY_WINDOW_SQL}
ORDER BY timestamp DESC
LIMIT 20
`

// Refresh cadence for the early view. Slower than the onboarding signal poll: this
// fans out to three property-reading queries, and "within a minute" is live enough.
const REFRESH_INTERVAL_MS = 60000

async function runQuery(query: string): Promise<unknown[][]> {
    const response = (await api.query(
        { kind: NodeKind.HogQLQuery, query },
        // Fresh on every poll: the whole point of this view is watching data arrive.
        { refresh: 'force_blocking' }
    )) as HogQLQueryResponse
    return (response?.results as unknown[][] | undefined) ?? []
}

// Tool responses are MCP content envelopes; pull out the human-readable text.
const extractErrorMessage = (raw: unknown): string | null => {
    const value = asOptionalString(raw)
    if (!value) {
        return null
    }
    try {
        const parsed = JSON.parse(value)
        const text = parsed?.content?.find?.((c: { type?: string }) => c?.type === 'text')?.text ?? parsed?.message
        if (typeof text === 'string' && text) {
            return text
        }
    } catch {
        // Not JSON — the raw string is the message.
    }
    return value
}

export const mcpEarlyDataLogic = kea<mcpEarlyDataLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'mcpEarlyDataLogic']),
    connect(() => ({
        values: [mcpAnalyticsOnboardingLogic, ['signals'], teamLogic, ['currentProjectId']],
        actions: [mcpAnalyticsOnboardingLogic, ['loadSignals']],
    })),
    actions({
        refreshAll: true,
    }),
    loaders(({ values }) => ({
        intentDigest: {
            __default: null as IntentDigest | null,
            loadIntentDigest: async (_: void, breakpoint): Promise<IntentDigest | null> => {
                if (!values.currentProjectId) {
                    return null
                }
                try {
                    const response = await mcpAnalyticsSessionsIntentDigest(String(values.currentProjectId))
                    breakpoint()
                    return { digest: response.digest, intentCount: response.intent_count }
                } catch {
                    // LLM unconfigured (503) or transient failure — the card falls back
                    // to the verbatim intent list.
                    return null
                }
            },
        },
    })),
    loaders({
        stats: {
            __default: EMPTY_STATS,
            loadStats: async (_: void, breakpoint): Promise<EarlyStats> => {
                const rows = await runQuery(EARLY_STATS_QUERY)
                breakpoint()
                const row = rows[0] ?? []
                return {
                    totalCalls: asNumber(row[0]),
                    distinctTools: asNumber(row[1]),
                    distinctSessions: asNumber(row[2]),
                    distinctClients: asNumber(row[3]),
                    callsWithIntent: asNumber(row[4]),
                    errorCalls: asNumber(row[5]),
                    missingCapabilityReports: asNumber(row[6]),
                }
            },
        },
        topTools: {
            __default: [] as EarlyToolRow[],
            loadTopTools: async (_: void, breakpoint): Promise<EarlyToolRow[]> => {
                const rows = await runQuery(TOP_TOOLS_QUERY)
                breakpoint()
                return rows.map((row) => ({
                    tool: String(row[0] ?? ''),
                    calls: asNumber(row[1]),
                    errors: asNumber(row[2]),
                }))
            },
        },
        clients: {
            __default: [] as EarlyClientRow[],
            loadClients: async (_: void, breakpoint): Promise<EarlyClientRow[]> => {
                const rows = await runQuery(CLIENTS_QUERY)
                breakpoint()
                return rows.map((row) => ({
                    client: asOptionalString(row[0]) ?? 'Unknown client',
                    calls: asNumber(row[1]),
                }))
            },
        },
        recentCalls: {
            __default: [] as EarlyRecentCall[],
            loadRecentCalls: async (_: void, breakpoint): Promise<EarlyRecentCall[]> => {
                const rows = await runQuery(RECENT_CALLS_QUERY)
                breakpoint()
                return rows.map((row) => ({
                    timestamp: String(row[0] ?? ''),
                    tool: String(row[1] ?? ''),
                    intent: asOptionalString(row[2]),
                    isError: asNumber(row[3]) > 0,
                    errorMessage: extractErrorMessage(row[4]),
                    durationMs: row[5] == null ? null : asNumber(row[5]),
                    clientName: asOptionalString(row[6]),
                }))
            },
        },
    }),
    selectors({
        // The onboarding signal poll and the stats query run on different cadences,
        // so during active ingestion they can briefly disagree. One number drives
        // the summary so the view never contradicts itself.
        totalCalls: [
            (s) => [s.signals, s.stats],
            (signals, stats): number => Math.max(stats.totalCalls, signals?.toolCallsTotal ?? 0),
        ],
        summary: [
            (s) => [s.totalCalls, s.stats, s.topTools],
            (totalCalls, stats, topTools): string =>
                buildActivitySummary({
                    totalCalls,
                    distinctClients: stats.distinctClients,
                    errorCalls: stats.errorCalls,
                    topTool: totalCalls > 10 ? (topTools[0]?.tool ?? null) : null,
                }),
        ],
        // Verbatim agent intents grouped by frequency — the fallback when no AI
        // digest is available. At low volume, reading what agents actually tried
        // beats any lossy aggregation of it.
        intentThemes: [
            (s) => [s.recentCalls],
            (recentCalls): IntentTheme[] => {
                const counts = new Map<string, number>()
                for (const call of recentCalls) {
                    if (call.intent) {
                        counts.set(call.intent, (counts.get(call.intent) ?? 0) + 1)
                    }
                }
                return [...counts.entries()]
                    .map(([intent, count]) => ({ intent, count }))
                    .sort((a, b) => b.count - a.count)
                    .slice(0, 6)
            },
        ],
        checklist: [(s) => [s.stats], (stats): ChecklistItem[] => buildChecklist(stats)],
        isRefreshing: [
            (s) => [s.statsLoading, s.topToolsLoading, s.recentCallsLoading, s.clientsLoading, s.intentDigestLoading],
            (statsLoading, topToolsLoading, recentCallsLoading, clientsLoading, intentDigestLoading): boolean =>
                statsLoading || topToolsLoading || recentCallsLoading || clientsLoading || intentDigestLoading,
        ],
    }),
    listeners(({ actions }) => ({
        refreshAll: () => {
            actions.loadSignals()
            actions.loadStats()
            actions.loadTopTools()
            actions.loadClients()
            actions.loadRecentCalls()
            // Server-side the digest is content-addressed, so this only reaches the
            // LLM when new intents have actually arrived.
            actions.loadIntentDigest()
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadStats()
        actions.loadTopTools()
        actions.loadClients()
        actions.loadRecentCalls()
        actions.loadIntentDigest()
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.refreshAll(), REFRESH_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'refresh')
    }),
])
