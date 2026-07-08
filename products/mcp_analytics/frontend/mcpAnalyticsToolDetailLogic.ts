import { afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import {
    MCPHarnessBreakdownItem,
    MCPToolDailyStatItem,
    MCPToolDescriptionItem,
    MCPToolFailureItem,
    MCPToolNeighborItem,
    MCPToolSampleIntentItem,
    MCPToolStatsItem,
    MCPToolTopUserItem,
    NodeKind,
} from '~/queries/schema/schema-general'

import type { mcpAnalyticsToolDetailLogicType } from './mcpAnalyticsToolDetailLogicType'

export interface ToolSummary {
    calls: number
    errors: number
    p50_ms: number | null
    p95_ms: number | null
    users: number
    conversations: number
}

export interface DescriptionRevision {
    description: string
    last_seen: string
}

export interface IntentCoverage {
    with_intent: number
    total: number
}

export interface DailyToolStat {
    day: string
    calls: number
    errors: number
    p50: number
    p95: number
    users: number
    sessions: number
}

export interface DailyChartData {
    labels: string[]
    calls: number[]
    errors: number[]
    p50: number[]
    p95: number[]
    users: number[]
    sessions: number[]
}

const EMPTY_CHART_DATA: DailyChartData = {
    labels: [],
    calls: [],
    errors: [],
    p50: [],
    p95: [],
    users: [],
    sessions: [],
}

export type ResultRows = unknown[][]

// Gap-fill the per-day rows into a continuous day axis (ClickHouse only returns days with data).
// Counts fill with 0; latency fills with NaN so the chart skips the point instead of dipping to 0.
export function buildDailyChartData(rows: DailyToolStat[]): DailyChartData {
    if (rows.length === 0) {
        return EMPTY_CHART_DATA
    }
    const byDay = new Map(rows.map((r) => [r.day, r]))
    const end = dayjs(rows[rows.length - 1].day)
    const labels: string[] = []
    for (let day = dayjs(rows[0].day); !day.isAfter(end); day = day.add(1, 'day')) {
        labels.push(day.format('YYYY-MM-DD'))
    }
    const at = labels.map((day) => byDay.get(day))
    return {
        labels,
        calls: at.map((r) => r?.calls ?? 0),
        errors: at.map((r) => r?.errors ?? 0),
        p50: at.map((r) => (r ? r.p50 : NaN)),
        p95: at.map((r) => (r ? r.p95 : NaN)),
        users: at.map((r) => r?.users ?? 0),
        sessions: at.map((r) => r?.sessions ?? 0),
    }
}

export interface MCPAnalyticsToolDetailLogicProps {
    toolName: string
}

// Absolute from/to for an exact N*24h window. A relative '-Nd' would be rounded to the start
// of the day by the backend's QueryDateRange, widening the window and letting per-section
// counts drift apart after midnight; the sections must share one window to stay consistent.
function windowDays(days: number): { date_from: string; date_to: string } {
    return { date_from: dayjs().subtract(days, 'day').toISOString(), date_to: dayjs().toISOString() }
}

// Tools most often called immediately before/after this one within the same conversation.
async function neighborRows(toolName: string, direction: 'before' | 'after'): Promise<ResultRows> {
    const response = (await api.query({
        kind: NodeKind.MCPToolNeighborsQuery,
        toolName,
        neighborDirection: direction,
        dateRange: windowDays(7),
    })) as { results?: MCPToolNeighborItem[] }
    return (response?.results ?? []).map((r) => [r.neighbor_tool, r.co_occurrences])
}

export const mcpAnalyticsToolDetailLogic = kea<mcpAnalyticsToolDetailLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsToolDetailLogic']),
    key((props: MCPAnalyticsToolDetailLogicProps) => props.toolName),
    props({} as MCPAnalyticsToolDetailLogicProps),

    loaders(({ props }) => ({
        summary: [
            null as ToolSummary | null,
            {
                loadSummary: async (): Promise<ToolSummary | null> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolStatsQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPToolStatsItem[] }
                    const row = response?.results?.[0]
                    if (!row) {
                        return null
                    }
                    return {
                        calls: row.calls,
                        errors: row.errors,
                        p50_ms: row.p50_ms,
                        p95_ms: row.p95_ms,
                        users: row.users,
                        conversations: row.conversations,
                    }
                },
            },
        ],
        descriptions: [
            [] as DescriptionRevision[],
            {
                loadDescriptions: async (): Promise<DescriptionRevision[]> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolDescriptionsQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(30),
                    })) as { results?: MCPToolDescriptionItem[] }
                    return (response?.results ?? []).map((r) => ({
                        description: r.description,
                        last_seen: r.last_seen,
                    }))
                },
            },
        ],
        intentCoverage: [
            null as IntentCoverage | null,
            {
                // Reads the same MCPToolStatsQuery as `summary`; the coverage denominator is the call count.
                loadIntentCoverage: async (): Promise<IntentCoverage | null> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolStatsQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPToolStatsItem[] }
                    const row = response?.results?.[0]
                    if (!row) {
                        return null
                    }
                    return { with_intent: row.with_intent, total: row.calls }
                },
            },
        ],
        dailyStats: [
            [] as DailyToolStat[],
            {
                loadDailyStats: async (): Promise<DailyToolStat[]> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolDailyStatsQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(30),
                    })) as { results?: MCPToolDailyStatItem[] }
                    return (response?.results ?? []).map((r) => ({
                        day: r.day,
                        calls: r.calls,
                        errors: r.errors,
                        p50: r.p50,
                        p95: r.p95,
                        users: r.users,
                        sessions: r.sessions,
                    }))
                },
            },
        ],
        failureRows: [
            [] as ResultRows,
            {
                loadFailureRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolFailuresQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPToolFailureItem[] }
                    return (response?.results ?? []).map((r) => [r.message, r.occurrences, r.last_seen, r.harnesses])
                },
            },
        ],
        sampleIntentRows: [
            [] as ResultRows,
            {
                loadSampleIntentRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolSampleIntentsQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPToolSampleIntentItem[] }
                    return (response?.results ?? []).map((r) => [r.timestamp, r.intent, r.intent_source, r.harness])
                },
            },
        ],
        neighborsBeforeRows: [
            [] as ResultRows,
            {
                loadNeighborsBeforeRows: async (): Promise<ResultRows> => neighborRows(props.toolName, 'before'),
            },
        ],
        neighborsAfterRows: [
            [] as ResultRows,
            {
                loadNeighborsAfterRows: async (): Promise<ResultRows> => neighborRows(props.toolName, 'after'),
            },
        ],
        byHarnessRows: [
            [] as ResultRows,
            {
                // Server-resolved harness labels via the same runner as the dashboard (scoped to this
                // tool's new-SDK calls by toolName), so the pill matches the dashboard's bucketing exactly.
                loadByHarnessRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPHarnessBreakdownQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPHarnessBreakdownItem[] }
                    return (response?.results ?? []).map((r) => [
                        r.harness,
                        r.total_calls,
                        r.errors,
                        r.error_rate_pct,
                        r.sessions,
                    ])
                },
            },
        ],
        topUserRows: [
            [] as ResultRows,
            {
                // The person tuple is rebuilt into the [distinct_id, _, properties] shape renderPersonCell expects.
                loadTopUserRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolTopUsersQuery,
                        toolName: props.toolName,
                        dateRange: windowDays(7),
                    })) as { results?: MCPToolTopUserItem[] }
                    return (response?.results ?? []).map((r) => [
                        [r.distinct_id, '', r.person_properties],
                        r.calls,
                        r.errors,
                        r.error_rate_pct,
                        r.harnesses,
                        r.last_seen,
                    ])
                },
            },
        ],
    })),

    selectors({
        toolName: [() => [(_, props) => props.toolName], (toolName: string) => toolName],

        dailyChartData: [
            (s) => [s.dailyStats],
            (dailyStats: DailyToolStat[]): DailyChartData => buildDailyChartData(dailyStats),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSummary()
        actions.loadDescriptions()
        actions.loadIntentCoverage()
        actions.loadDailyStats()
        actions.loadFailureRows()
        actions.loadSampleIntentRows()
        actions.loadNeighborsBeforeRows()
        actions.loadNeighborsAfterRows()
        actions.loadByHarnessRows()
        actions.loadTopUserRows()
    }),
])
