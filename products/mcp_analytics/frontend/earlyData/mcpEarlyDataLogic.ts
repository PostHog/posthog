import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsSessionsActivityOverview, mcpAnalyticsSessionsIntentDigest } from '../generated/api'
import type { MCPActivityOverviewApi } from '../generated/api.schemas'
import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
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

// Refresh cadence for the early view. Slower than the onboarding signal poll: the
// overview aggregates 30 days of property-reading queries server-side, and "within
// a minute" is live enough.
const REFRESH_INTERVAL_MS = 60000

export const mcpEarlyDataLogic = kea<mcpEarlyDataLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'mcpEarlyDataLogic']),
    connect(() => ({
        values: [mcpAnalyticsOnboardingLogic, ['signals'], teamLogic, ['currentProjectId']],
        // loadSignals is dispatched from refreshAll so the summary's totalCalls
        // (max of both sources) advances together with the overview.
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
        overview: {
            __default: null as MCPActivityOverviewApi | null,
            loadOverview: async (_: void, breakpoint): Promise<MCPActivityOverviewApi | null> => {
                if (!values.currentProjectId) {
                    return null
                }
                const response = await mcpAnalyticsSessionsActivityOverview(String(values.currentProjectId))
                breakpoint()
                return response
            },
        },
    })),
    selectors({
        stats: [
            (s) => [s.overview],
            (overview): EarlyStats =>
                overview
                    ? {
                          totalCalls: overview.stats.total_calls,
                          distinctTools: overview.stats.distinct_tools,
                          distinctSessions: overview.stats.distinct_sessions,
                          distinctClients: overview.stats.distinct_clients,
                          callsWithIntent: overview.stats.calls_with_intent,
                          errorCalls: overview.stats.error_calls,
                          missingCapabilityReports: overview.stats.missing_capability_reports,
                      }
                    : EMPTY_STATS,
        ],
        topTools: [
            (s) => [s.overview],
            (overview): EarlyToolRow[] =>
                (overview?.top_tools ?? []).map((row) => ({ tool: row.tool, calls: row.calls, errors: row.errors })),
        ],
        clients: [
            (s) => [s.overview],
            (overview): EarlyClientRow[] =>
                (overview?.clients ?? []).map((row) => ({ client: row.client || 'Unknown client', calls: row.calls })),
        ],
        recentCalls: [
            (s) => [s.overview],
            (overview): EarlyRecentCall[] =>
                (overview?.recent_calls ?? []).map((row) => ({
                    timestamp: row.timestamp,
                    tool: row.tool,
                    intent: row.intent,
                    isError: row.is_error,
                    errorMessage: row.error_message,
                    durationMs: row.duration_ms,
                    clientName: row.client_name,
                })),
        ],
        // The onboarding signal poll and the overview query run on different cadences,
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
            (s) => [s.overviewLoading, s.intentDigestLoading],
            (overviewLoading, intentDigestLoading): boolean => overviewLoading || intentDigestLoading,
        ],
    }),
    listeners(({ actions }) => ({
        refreshAll: () => {
            actions.loadSignals()
            actions.loadOverview()
            // Server-side the digest is content-addressed, so this only reaches the
            // LLM when new intents have actually arrived.
            actions.loadIntentDigest()
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadOverview()
        actions.loadIntentDigest()
        cache.disposables.add(() => {
            const id = window.setInterval(() => actions.refreshAll(), REFRESH_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'refresh')
    }),
])
