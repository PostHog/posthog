import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'

import { mcpClusteringLogic } from './clustering/mcpClusteringLogic'
import type { MCPIntentClusterApi, MCPIntentClusterJourneyPathApi } from './generated/api.schemas'
import type { JourneyPath } from './JourneySankey'
import type { mcpDashboardOverviewLogicType } from './mcpDashboardOverviewLogicType'

const LOOKBACK_DAYS = 7

const KPI_QUERY = hogql`
SELECT
    toDate(timestamp) AS bucket,
    countDistinctIf(toString(properties.$session_id), toString(properties.$session_id) != '') AS sessions,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95,
    timestamp >= now() - INTERVAL ${hogql.raw(String(LOOKBACK_DAYS))} DAY AS in_current
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL ${hogql.raw(String(LOOKBACK_DAYS * 2))} DAY
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
GROUP BY bucket, in_current
ORDER BY bucket
`

// Per-session rollup powering the Notable sessions block. The selector
// applies fixed rules over this set; no per-rule SQL.
const SESSION_ROWS_QUERY = hogql`
SELECT
    toString(properties.$session_id) AS session_id,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    uniq(toString(properties.$mcp_tool_name)) AS distinct_tools,
    max(timestamp) AS last_seen
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL ${hogql.raw(String(LOOKBACK_DAYS))} DAY
    AND properties.$session_id IS NOT NULL
    AND properties.$session_id != ''
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
GROUP BY session_id
HAVING tool_calls >= 1
ORDER BY tool_calls DESC
LIMIT 500
`

// Mirrors products/mcp_analytics/backend/queries/tool_quality.sql for the
// compact reliability matrix on the overview. Limited columns + 50 rows.
const TOOL_ROWS_QUERY = hogql`
SELECT
    toString(properties.$mcp_tool_name) AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL ${hogql.raw(String(LOOKBACK_DAYS))} DAY
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
GROUP BY tool
ORDER BY total_calls DESC
LIMIT 50
`

interface BucketRow {
    bucket: string
    sessions: number
    tool_calls: number
    errors: number
    p95: number
    in_current: boolean
}

export interface KPIMetric {
    value: number
    previousValue: number
    deltaPct: number | null
    sparkline: number[]
    goodDirection: 'up' | 'down'
}

export interface KPIData {
    sessions: KPIMetric
    toolCalls: KPIMetric
    errorRatePct: KPIMetric
    p95LatencyMs: KPIMetric
}

export interface ToolRow {
    tool: string
    total_calls: number
    errors: number
    error_rate_pct: number
    p95_duration_ms: number
}

export interface SessionRow {
    session_id: string
    tool_calls: number
    errors: number
    error_rate_pct: number
    duration_seconds: number
    distinct_tools: number
    last_seen: string
}

export type NotableRule = 'worst_error_rate' | 'all_fail' | 'most_exploratory' | 'exemplar'

export interface NotableSession {
    rule: NotableRule
    label: string
    session: SessionRow
}

export interface DashboardJourney {
    paths: JourneyPath[]
    totalSessions: number
    leak: JourneyPath | null
}

const MAX_DASHBOARD_JOURNEY_PATHS = 10
const MIN_PATH_SHARE_PCT = 1

const EMPTY_METRIC: KPIMetric = { value: 0, previousValue: 0, deltaPct: null, sparkline: [], goodDirection: 'up' }
const EMPTY_KPIS: KPIData = {
    sessions: { ...EMPTY_METRIC, goodDirection: 'up' },
    toolCalls: { ...EMPTY_METRIC, goodDirection: 'up' },
    errorRatePct: { ...EMPTY_METRIC, goodDirection: 'down' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}

function deltaPct(current: number, previous: number): number | null {
    if (previous === 0) {
        return current === 0 ? 0 : null
    }
    return ((current - previous) / previous) * 100
}

function parseRows(rawRows: unknown[][]): BucketRow[] {
    return rawRows.map((r) => ({
        bucket: String(r[0]),
        sessions: Number(r[1] ?? 0),
        tool_calls: Number(r[2] ?? 0),
        errors: Number(r[3] ?? 0),
        p95: Number(r[4] ?? 0),
        in_current: Boolean(r[5]),
    }))
}

function buildKPIs(rows: BucketRow[]): KPIData {
    const current = rows.filter((r) => r.in_current).sort((a, b) => a.bucket.localeCompare(b.bucket))
    const previous = rows.filter((r) => !r.in_current)

    const curSessions = current.reduce((acc, r) => acc + r.sessions, 0)
    const curCalls = current.reduce((acc, r) => acc + r.tool_calls, 0)
    const curErrors = current.reduce((acc, r) => acc + r.errors, 0)
    const curP95 = current.length ? Math.max(...current.map((r) => r.p95)) : 0

    const prevSessions = previous.reduce((acc, r) => acc + r.sessions, 0)
    const prevCalls = previous.reduce((acc, r) => acc + r.tool_calls, 0)
    const prevErrors = previous.reduce((acc, r) => acc + r.errors, 0)
    const prevP95 = previous.length ? Math.max(...previous.map((r) => r.p95)) : 0

    const curErrorRate = curCalls ? (curErrors / curCalls) * 100 : 0
    const prevErrorRate = prevCalls ? (prevErrors / prevCalls) * 100 : 0

    return {
        sessions: {
            value: curSessions,
            previousValue: prevSessions,
            deltaPct: deltaPct(curSessions, prevSessions),
            sparkline: current.map((r) => r.sessions),
            goodDirection: 'up',
        },
        toolCalls: {
            value: curCalls,
            previousValue: prevCalls,
            deltaPct: deltaPct(curCalls, prevCalls),
            sparkline: current.map((r) => r.tool_calls),
            goodDirection: 'up',
        },
        errorRatePct: {
            value: curErrorRate,
            previousValue: prevErrorRate,
            deltaPct: deltaPct(curErrorRate, prevErrorRate),
            sparkline: current.map((r) => (r.tool_calls ? (r.errors / r.tool_calls) * 100 : 0)),
            goodDirection: 'down',
        },
        p95LatencyMs: {
            value: curP95,
            previousValue: prevP95,
            deltaPct: deltaPct(curP95, prevP95),
            sparkline: current.map((r) => r.p95),
            goodDirection: 'down',
        },
    }
}

export const mcpDashboardOverviewLogic = kea<mcpDashboardOverviewLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpDashboardOverviewLogic']),
    connect(() => ({
        values: [mcpClusteringLogic, ['clusters', 'hasSnapshot']],
    })),
    loaders({
        kpis: [
            EMPTY_KPIS,
            {
                loadKPIs: async () => {
                    const response = await hogqlQuery(KPI_QUERY)
                    const rows = parseRows((response?.results as unknown[][]) ?? [])
                    return buildKPIs(rows)
                },
            },
        ],
        toolRows: [
            [] as ToolRow[],
            {
                loadToolRows: async () => {
                    const response = await hogqlQuery(TOOL_ROWS_QUERY)
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        tool: String(r[0] ?? ''),
                        total_calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        error_rate_pct: Number(r[3] ?? 0),
                        p95_duration_ms: Number(r[4] ?? 0),
                    }))
                },
            },
        ],
        sessionRows: [
            [] as SessionRow[],
            {
                loadSessionRows: async () => {
                    const response = await hogqlQuery(SESSION_ROWS_QUERY)
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        session_id: String(r[0] ?? ''),
                        tool_calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        error_rate_pct: Number(r[3] ?? 0),
                        duration_seconds: Number(r[4] ?? 0),
                        distinct_tools: Number(r[5] ?? 0),
                        last_seen: String(r[6] ?? ''),
                    }))
                },
            },
        ],
    }),
    selectors({
        topToolRows: [(s) => [s.toolRows], (toolRows: ToolRow[]): ToolRow[] => toolRows.slice(0, 5)],
        toolRowsTotal: [(s) => [s.toolRows], (toolRows: ToolRow[]): number => toolRows.length],
        notableSessions: [
            (s) => [s.sessionRows],
            (sessionRows: SessionRow[]): NotableSession[] => pickNotableSessions(sessionRows),
        ],
        dashboardJourney: [
            (s) => [s.clusters],
            (clusters: readonly MCPIntentClusterApi[]): DashboardJourney => buildDashboardJourney(clusters),
        ],
        intentClusterCount: [
            (s) => [s.clusters],
            (clusters: readonly MCPIntentClusterApi[]): KPIMetric => ({
                value: clusters.length,
                previousValue: 0,
                deltaPct: null,
                sparkline: [],
                goodDirection: 'up',
            }),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadKPIs()
        actions.loadToolRows()
        actions.loadSessionRows()
    }),
])

function median(values: number[]): number {
    if (values.length === 0) {
        return 0
    }
    const sorted = [...values].sort((a, b) => a - b)
    const mid = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

// Build a team-wide Sankey from the per-cluster journeys already computed by
// the intent clustering snapshot. Same (steps, outcome) tuple across different
// clusters is summed. This is intentionally a composition of existing data —
// no new HogQL — and inherits the snapshot's `completed`/`error` outcomes.
function buildDashboardJourney(clusters: readonly MCPIntentClusterApi[]): DashboardJourney {
    if (clusters.length === 0) {
        return { paths: [], totalSessions: 0, leak: null }
    }

    const byKey = new Map<string, JourneyPath>()
    let totalSessions = 0

    for (const cluster of clusters) {
        const journey = cluster.journey
        if (!journey) {
            continue
        }
        totalSessions += journey.total_sessions
        for (const path of journey.paths) {
            byKey.set(pathKey(path), mergePath(byKey.get(pathKey(path)), path))
        }
    }

    if (totalSessions === 0 || byKey.size === 0) {
        return { paths: [], totalSessions: 0, leak: null }
    }

    const minCount = Math.max(1, Math.ceil((totalSessions * MIN_PATH_SHARE_PCT) / 100))
    const allPaths = [...byKey.values()].sort((a, b) => b.count - a.count)
    const paths = allPaths.filter((p) => p.count >= minCount).slice(0, MAX_DASHBOARD_JOURNEY_PATHS)

    // Leak: highest-volume error path (always render *something* per spec). Fall
    // back to the single biggest path when no error path exists at all.
    const errorPaths = allPaths.filter((p) => p.outcome === 'error')
    const leak = errorPaths[0] ?? null

    return { paths: paths.length ? paths : allPaths.slice(0, MAX_DASHBOARD_JOURNEY_PATHS), totalSessions, leak }
}

function pathKey(path: MCPIntentClusterJourneyPathApi | JourneyPath): string {
    return `${path.outcome}::${path.steps.map((s) => s ?? '∅').join('>')}`
}

function mergePath(existing: JourneyPath | undefined, incoming: MCPIntentClusterJourneyPathApi): JourneyPath {
    if (!existing) {
        return { steps: [...incoming.steps], outcome: incoming.outcome, count: incoming.count }
    }
    return { ...existing, count: existing.count + incoming.count }
}

// Pick at most one session per rule. Thresholds relax automatically when the
// data is small so something demo-worthy always shows.
function pickNotableSessions(rows: SessionRow[]): NotableSession[] {
    if (rows.length === 0) {
        return []
    }

    const medianCalls = median(rows.map((r) => r.tool_calls))
    const medianDuration = median(rows.map((r) => r.duration_seconds))
    const used = new Set<string>()
    const picked: NotableSession[] = []

    const take = (rule: NotableRule, label: string, candidate: SessionRow | undefined): void => {
        if (!candidate || used.has(candidate.session_id)) {
            return
        }
        used.add(candidate.session_id)
        picked.push({ rule, label, session: candidate })
    }

    // 1. Worst error rate at high volume — top err% among above-median-volume sessions
    const highVolume = rows.filter((r) => r.tool_calls >= Math.max(medianCalls, 3) && r.error_rate_pct > 0)
    take(
        'worst_error_rate',
        'Worst error rate at high volume',
        [...highVolume].sort((a, b) => b.error_rate_pct - a.error_rate_pct || b.tool_calls - a.tool_calls)[0]
    )

    // 2. All-fail session — error_rate_pct === 100 AND tool_calls >= 3
    const allFail = rows.filter((r) => r.error_rate_pct >= 100 && r.tool_calls >= 3)
    take(
        'all_fail',
        'Every call failed — likely auth scope',
        [...allFail].sort((a, b) => b.tool_calls - a.tool_calls)[0]
    )

    // 3. Most exploratory — highest distinct_tools count (multi-step journey)
    take(
        'most_exploratory',
        'Most exploratory journey',
        [...rows].sort((a, b) => b.distinct_tools - a.distinct_tools || b.tool_calls - a.tool_calls)[0]
    )

    // 4. Exemplar — zero errors, above-median calls, faster than median duration
    const exemplars = rows.filter(
        (r) =>
            r.error_rate_pct === 0 && r.tool_calls >= Math.max(medianCalls, 3) && r.duration_seconds <= medianDuration
    )
    take('exemplar', 'Exemplar — concise success', [...exemplars].sort((a, b) => b.tool_calls - a.tool_calls)[0])

    return picked
}
