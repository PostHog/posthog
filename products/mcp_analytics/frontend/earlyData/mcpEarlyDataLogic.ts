import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { ChecklistItem, EarlyStats, buildChecklist } from './earlyDataChecklist'
import { Milestone, buildMilestones, nextMilestone, progressToNextMilestone } from './earlyDataMilestones'
import type { mcpEarlyDataLogicType } from './mcpEarlyDataLogicType'

export type { ChecklistItem, EarlyStats } from './earlyDataChecklist'

export interface EarlyRecentCall {
    timestamp: string
    tool: string
    intent: string | null
    isError: boolean
    durationMs: number | null
    clientName: string | null
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
// matching row — affordable here only because this logic mounts exclusively in early
// mode, where lifetime volume is below the graduation threshold by definition. Windows
// are deliberately all-time: a server with 40 calls last month should still show them.
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
WHERE event IN ('$mcp_tool_call', '$mcp_missing_capability')
`

const TOP_TOOLS_QUERY = `
SELECT
    properties.$mcp_tool_name AS tool,
    count() AS calls,
    countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors
FROM events
WHERE event = '$mcp_tool_call' AND properties.$mcp_tool_name IS NOT NULL
GROUP BY tool
ORDER BY calls DESC
LIMIT 5
`

const CLIENTS_QUERY = `
SELECT
    properties.$mcp_client_name AS client,
    count() AS calls
FROM events
WHERE event = '$mcp_tool_call'
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
    toFloat(properties.$mcp_duration_ms) AS duration_ms,
    properties.$mcp_client_name AS client_name
FROM events
WHERE event = '$mcp_tool_call'
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

const asNumber = (value: unknown): number => Number(value) || 0
const asOptionalString = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null)

export const mcpEarlyDataLogic = kea<mcpEarlyDataLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'mcpEarlyDataLogic']),
    connect(() => ({
        values: [mcpAnalyticsOnboardingLogic, ['signals']],
        actions: [mcpAnalyticsOnboardingLogic, ['loadSignals']],
    })),
    actions({
        refreshAll: true,
    }),
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
                    durationMs: row[4] == null ? null : asNumber(row[4]),
                    clientName: asOptionalString(row[5]),
                }))
            },
        },
    }),
    selectors({
        // The onboarding signal poll and the early stats query run on different cadences,
        // so during active ingestion they can briefly disagree. One number drives the
        // header, milestones, and progress so the view never contradicts itself.
        totalCalls: [
            (s) => [s.signals, s.stats],
            (signals, stats): number => Math.max(stats.totalCalls, signals?.toolCallsTotal ?? 0),
        ],
        milestones: [(s) => [s.totalCalls], (totalCalls): Milestone[] => buildMilestones(totalCalls)],
        nextMilestone: [(s) => [s.milestones], (milestones): Milestone | null => nextMilestone(milestones)],
        milestoneProgress: [
            (s) => [s.totalCalls, s.milestones],
            (totalCalls, milestones): number => progressToNextMilestone(totalCalls, milestones),
        ],
        checklist: [(s) => [s.stats], (stats): ChecklistItem[] => buildChecklist(stats)],
        isRefreshing: [
            (s) => [s.statsLoading, s.topToolsLoading, s.recentCallsLoading, s.clientsLoading],
            (statsLoading, topToolsLoading, recentCallsLoading, clientsLoading): boolean =>
                statsLoading || topToolsLoading || recentCallsLoading || clientsLoading,
        ],
    }),
    listeners(({ actions }) => ({
        refreshAll: () => {
            actions.loadSignals()
            actions.loadStats()
            actions.loadTopTools()
            actions.loadClients()
            actions.loadRecentCalls()
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadStats()
        actions.loadTopTools()
        actions.loadClients()
        actions.loadRecentCalls()
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.refreshAll(), REFRESH_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'refresh')
    }),
])
