import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLFilters, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { mcpClusteringLogic } from './clustering/mcpClusteringLogic'
import type { MCPIntentClusterApi } from './generated/api.schemas'
import type { mcpDashboardOverviewLogicType } from './mcpDashboardOverviewLogicType'

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }

// KPI tiles compare the selected window against the immediately preceding window
// of equal length. The current/previous split is applied in `buildKPIs` against
// the time buckets, so the query only needs the doubled date range. `__BUCKET__`
// is replaced with the granularity's bucket function at call time.
const KPI_QUERY = `
SELECT
    __BUCKET__ AS bucket,
    countDistinctIf(toString(properties.$mcp_session_id), toString(properties.$mcp_session_id) != '') AS sessions,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY bucket
ORDER BY bucket
`

// Per-session rollup powering the Notable sessions block. The selector
// applies fixed rules over this set; no per-rule SQL.
const SESSION_ROWS_QUERY = `
SELECT
    toString(properties.$mcp_session_id) AS session_id,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    uniq(toString(properties.$mcp_tool_name)) AS distinct_tools,
    max(timestamp) AS last_seen
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_session_id IS NOT NULL
    AND properties.$mcp_session_id != ''
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY session_id
HAVING tool_calls >= 1
ORDER BY tool_calls DESC
LIMIT 500
`

// Mirrors products/mcp_analytics/backend/templates/tool_quality.sql for the
// compact reliability matrix on the overview. Limited columns + 50 rows.
const TOOL_ROWS_QUERY = `
SELECT
    toString(properties.$mcp_tool_name) AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY tool
ORDER BY total_calls DESC
LIMIT 50
`

const HARNESS_ROWS_QUERY = `
SELECT
    toString(properties.$mcp_client_name) AS client,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    countDistinctIf(toString(properties.$mcp_session_id), toString(properties.$mcp_session_id) != '') AS sessions
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_client_name IS NOT NULL
    AND properties.$mcp_client_name != ''
    AND {filters}
GROUP BY client
ORDER BY total_calls DESC
LIMIT 200
`

// Daily success/error split powering the activity time-series bar chart.
const ACTIVITY_QUERY = `
SELECT
    __BUCKET__ AS day,
    countIf(NOT toBool(properties.$mcp_is_error)) AS successes,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY day
ORDER BY day
`

// Daily call counts per tool, powering the tool-usage stacked bar (one segment per tool).
const TOOL_DAILY_QUERY = `
SELECT
    __BUCKET__ AS day,
    toString(properties.$mcp_tool_name) AS tool,
    count() AS calls
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY day, tool
ORDER BY day
LIMIT 10000
`

export interface BucketRow {
    bucket: string
    sessions: number
    tool_calls: number
    errors: number
    p95: number
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

export interface HarnessRawRow {
    client: string
    total_calls: number
    errors: number
    sessions: number
}

export interface ActivityRow {
    day: string
    successes: number
    errors: number
}

export interface DailyActivity {
    labels: string[]
    successes: number[]
    errors: number[]
}

export interface ToolDailyRow {
    day: string
    tool: string
    calls: number
}

export interface ToolDailySeries {
    labels: string[]
    tools: { tool: string; data: number[] }[]
}

export interface HarnessRow {
    category: string
    total_calls: number
    errors: number
    error_rate_pct: number
    sessions: number
    raw_clients: string[]
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

export type NotableRule = 'worst_error_rate' | 'all_fail' | 'most_exploratory' | 'exemplar' | 'high_activity'

// Fill the table out to this many rows: the rule-based picks first, then the busiest remaining sessions.
const NOTABLE_SESSION_TARGET = 8

export interface NotableSession {
    rule: NotableRule
    label: string
    session: SessionRow
}

const EMPTY_METRIC: KPIMetric = { value: 0, previousValue: 0, deltaPct: null, sparkline: [], goodDirection: 'up' }
const EMPTY_KPIS: KPIData = {
    sessions: { ...EMPTY_METRIC, goodDirection: 'up' },
    toolCalls: { ...EMPTY_METRIC, goodDirection: 'up' },
    errorRatePct: { ...EMPTY_METRIC, goodDirection: 'down' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}

// Harness categories derived from sampling the top 50 distinct $mcp_client_name
// values seen in production over the past 30 days. We normalize the
// "(via mcp-remote …)" suffix that mcp-remote injects so the underlying client
// folds into its real harness bucket.
const HARNESS_CATEGORIES: { category: string; match: (name: string) => boolean }[] = [
    { category: 'Claude Code', match: (n) => n.startsWith('claude-code') },
    {
        category: 'Claude.ai',
        match: (n) => n === 'claude-ai' || n === 'anthropic/claudeai',
    },
    { category: 'Anthropic API', match: (n) => n === 'anthropic/api' },
    {
        category: 'OpenAI Codex',
        match: (n) => n.startsWith('codex') || n.startsWith('openai-mcp'),
    },
    { category: 'Cursor', match: (n) => n.startsWith('cursor') },
    { category: 'VS Code', match: (n) => n.startsWith('visual studio code') },
    { category: 'Windsurf', match: (n) => n === 'windsurf' },
    { category: 'Replit', match: (n) => n.startsWith('replit') },
    { category: 'Lovable', match: (n) => n.startsWith('lovable') },
    { category: 'Manus', match: (n) => n === 'manus' },
    { category: 'CodeRabbit', match: (n) => n === 'coderabbit' },
    { category: 'Notion', match: (n) => n.startsWith('notion') },
    { category: 'Poke', match: (n) => n === 'poke' },
    { category: 'opencode', match: (n) => n === 'opencode' },
    { category: 'Kiro', match: (n) => n.startsWith('kiro') },
    { category: 'Desktop Commander', match: (n) => n.startsWith('desktop-commander') },
]

export function categorizeHarness(raw: string): string {
    const stripped = raw
        .replace(/\s*\(via mcp-remote[^)]*\)\s*/i, '')
        .trim()
        .toLowerCase()
    if (!stripped) {
        return 'Other'
    }
    for (const entry of HARNESS_CATEGORIES) {
        if (entry.match(stripped)) {
            return entry.category
        }
    }
    return 'Other'
}

export function aggregateHarnessRows(raw: HarnessRawRow[]): HarnessRow[] {
    const byCategory = new Map<string, HarnessRow>()
    for (const row of raw) {
        const category = categorizeHarness(row.client)
        const existing = byCategory.get(category)
        if (existing) {
            existing.total_calls += row.total_calls
            existing.errors += row.errors
            existing.sessions += row.sessions
            existing.raw_clients.push(row.client)
        } else {
            byCategory.set(category, {
                category,
                total_calls: row.total_calls,
                errors: row.errors,
                error_rate_pct: 0,
                sessions: row.sessions,
                raw_clients: [row.client],
            })
        }
    }
    const result = [...byCategory.values()]
    for (const r of result) {
        r.error_rate_pct = r.total_calls ? Math.round((r.errors / r.total_calls) * 1000) / 10 : 0
    }
    result.sort((a, b) => b.total_calls - a.total_calls)
    return result
}

// Keep the stacked bar legible: only the busiest tools get their own segment; the long tail is
// folded into a single "Other" series so the chart can't sprout dozens of repeating-colour bands.
const TOOL_SERIES_LIMIT = 8

// Pivot flat (day, tool, calls) rows into a label array + one data series per tool, tools ordered
// by total volume (biggest first) so the stack and legend read consistently.
export function buildToolDailySeries(rows: ToolDailyRow[]): ToolDailySeries {
    const days = [...new Set(rows.map((r) => r.day))].sort()
    const totalByTool = new Map<string, number>()
    const byToolDay = new Map<string, Map<string, number>>()
    for (const row of rows) {
        totalByTool.set(row.tool, (totalByTool.get(row.tool) ?? 0) + row.calls)
        let dayMap = byToolDay.get(row.tool)
        if (!dayMap) {
            dayMap = new Map<string, number>()
            byToolDay.set(row.tool, dayMap)
        }
        dayMap.set(row.day, (dayMap.get(row.day) ?? 0) + row.calls)
    }
    const seriesFor = (tool: string): number[] => days.map((day) => byToolDay.get(tool)!.get(day) ?? 0)
    const ranked = [...totalByTool.entries()].sort((a, b) => b[1] - a[1]).map(([tool]) => tool)
    const tools = ranked.slice(0, TOOL_SERIES_LIMIT).map((tool) => ({ tool, data: seriesFor(tool) }))
    const rest = ranked.slice(TOOL_SERIES_LIMIT)
    if (rest.length > 0) {
        tools.push({ tool: 'Other', data: days.map((_, i) => rest.reduce((sum, t) => sum + seriesFor(t)[i], 0)) })
    }
    return { labels: days, tools }
}

export function deltaPct(current: number, previous: number): number | null {
    if (previous === 0) {
        return current === 0 ? 0 : null
    }
    return ((current - previous) / previous) * 100
}

// Short windows get fine buckets so ranges like "last hour" stay legible; longer
// windows fall back to coarser buckets to keep the point count sane.
export type BucketGranularity = 'minute' | 'hour' | 'day'

// ClickHouse bucket function per granularity. These are fixed expressions (never
// user input), so they're safe to interpolate into the query string.
const BUCKET_EXPR: Record<BucketGranularity, string> = {
    minute: 'toStartOfMinute(timestamp)',
    hour: 'toStartOfHour(timestamp)',
    day: 'toDate(timestamp)',
}

// dayjs format that reproduces each bucket function's string output, so the
// `buildKPIs` cutoff compares like-for-like against the bucket column.
const BUCKET_CUTOFF_FORMAT: Record<BucketGranularity, string> = {
    minute: 'YYYY-MM-DD HH:mm:00',
    hour: 'YYYY-MM-DD HH:00:00',
    day: 'YYYY-MM-DD',
}

// Resolve the filter to absolute bounds. Hour-level relative ranges ("-1h") are
// rolling from now; dateStringToDayJs anchors relative dates to the start of the
// day, which would inflate a "last hour" window to half a day. Day+ ranges keep
// that start-of-day anchoring (the established behaviour).
function resolveWindow(dateFilter: DateFilter, timezone: string): { start: dayjs.Dayjs; end: dayjs.Dayjs } {
    const now = dayjs().tz(timezone)
    const end = (dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo, timezone) : now) ?? now
    const components = dateStringToComponents(dateFilter.dateFrom)
    if (components && components.unit === 'hour' && !dateFilter.dateTo) {
        // components.amount is signed (negative for the past), so add() walks backwards.
        return { start: now.add(components.amount, 'hour'), end: now }
    }
    const start = dateStringToDayJs(dateFilter.dateFrom, timezone) ?? now.subtract(7, 'day')
    return { start, end }
}

export function bucketGranularityForWindow(dateFilter: DateFilter, timezone: string): BucketGranularity {
    const { start, end } = resolveWindow(dateFilter, timezone)
    const hours = end.diff(start, 'hour')
    if (hours <= 3) {
        return 'minute'
    }
    if (hours <= 72) {
        return 'hour'
    }
    return 'day'
}

export interface KpiWindow {
    dateFrom: string
    dateTo: string
    currentStartBucket: string
}

// Resolve the selected window to absolute bounds, then extend the query range back
// so a single query returns both the selected period and an equal-length prior
// period (measured in whole buckets of the active granularity). `currentStartBucket`
// is the cutoff `buildKPIs` uses to split them.
export function buildKpiWindow(dateFilter: DateFilter, timezone: string, granularity: BucketGranularity): KpiWindow {
    const { start, end } = resolveWindow(dateFilter, timezone)
    // The selected period covers the inclusive buckets [start, end] — one more than
    // end.diff(start). Step the prior window back by that same count so the two
    // halves of the comparison span an equal number of buckets.
    const selectedBuckets = Math.max(1, end.diff(start, granularity) + 1)
    const priorStart = start.subtract(selectedBuckets, granularity)
    return {
        dateFrom: priorStart.toISOString(),
        dateTo: end.toISOString(),
        currentStartBucket: start.startOf(granularity).format(BUCKET_CUTOFF_FORMAT[granularity]),
    }
}

function parseRows(rawRows: unknown[][]): BucketRow[] {
    return rawRows.map((r) => ({
        bucket: String(r[0]),
        sessions: Number(r[1] ?? 0),
        tool_calls: Number(r[2] ?? 0),
        errors: Number(r[3] ?? 0),
        p95: Number(r[4] ?? 0),
    }))
}

// Buckets at or after `currentStartBucket` belong to the selected window; the
// rest are the equal-length window immediately before it.
export function buildKPIs(rows: BucketRow[], currentStartBucket: string): KPIData {
    const current = rows.filter((r) => r.bucket >= currentStartBucket).sort((a, b) => a.bucket.localeCompare(b.bucket))
    const previous = rows.filter((r) => r.bucket < currentStartBucket)

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
        values: [mcpClusteringLogic, ['clusters', 'hasSnapshot'], teamLogic, ['timezone']],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        reloadAll: true,
    }),
    reducers({
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
    }),
    loaders(({ values }) => ({
        kpis: [
            EMPTY_KPIS,
            {
                loadKPIs: async (_: void, breakpoint) => {
                    const granularity = values.bucketGranularity
                    const kpiWindow = buildKpiWindow(values.dateFilter, values.timezone, granularity)
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: KPI_QUERY.replace('__BUCKET__', BUCKET_EXPR[granularity]),
                        filters: {
                            ...values.queryFilters,
                            dateRange: { date_from: kpiWindow.dateFrom, date_to: kpiWindow.dateTo },
                        },
                    })) as HogQLQueryResponse
                    breakpoint()
                    const rows = parseRows((response?.results as unknown[][]) ?? [])
                    return buildKPIs(rows, kpiWindow.currentStartBucket)
                },
            },
        ],
        toolRows: [
            [] as ToolRow[],
            {
                loadToolRows: async (_: void, breakpoint) => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: TOOL_ROWS_QUERY,
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
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
                loadSessionRows: async (_: void, breakpoint) => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: SESSION_ROWS_QUERY,
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
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
        harnessRawRows: [
            [] as HarnessRawRow[],
            {
                loadHarnessRows: async (_: void, breakpoint) => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: HARNESS_ROWS_QUERY,
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        client: String(r[0] ?? ''),
                        total_calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        sessions: Number(r[3] ?? 0),
                    }))
                },
            },
        ],
        activityRows: [
            [] as ActivityRow[],
            {
                loadActivityRows: async (_: void, breakpoint): Promise<ActivityRow[]> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: ACTIVITY_QUERY.replace('__BUCKET__', BUCKET_EXPR[values.bucketGranularity]),
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        day: String(r[0] ?? ''),
                        successes: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                    }))
                },
            },
        ],
        toolDailyRows: [
            [] as ToolDailyRow[],
            {
                loadToolDailyRows: async (_: void, breakpoint): Promise<ToolDailyRow[]> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: TOOL_DAILY_QUERY.replace('__BUCKET__', BUCKET_EXPR[values.bucketGranularity]),
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        day: String(r[0] ?? ''),
                        tool: String(r[1] ?? ''),
                        calls: Number(r[2] ?? 0),
                    }))
                },
            },
        ],
    })),
    selectors({
        queryFilters: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): HogQLFilters => ({
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
            }),
        ],
        bucketGranularity: [
            (s) => [s.dateFilter, s.timezone],
            (dateFilter: DateFilter, timezone: string): BucketGranularity =>
                bucketGranularityForWindow(dateFilter, timezone),
        ],
        harnessRows: [(s) => [s.harnessRawRows], (raw: HarnessRawRow[]): HarnessRow[] => aggregateHarnessRows(raw)],
        dailyActivity: [
            (s) => [s.activityRows],
            (rows: ActivityRow[]): DailyActivity => ({
                labels: rows.map((r) => r.day),
                successes: rows.map((r) => r.successes),
                errors: rows.map((r) => r.errors),
            }),
        ],
        toolDailySeries: [
            (s) => [s.toolDailyRows],
            (rows: ToolDailyRow[]): ToolDailySeries => buildToolDailySeries(rows),
        ],
        notableSessions: [
            (s) => [s.sessionRows],
            (sessionRows: SessionRow[]): NotableSession[] => pickNotableSessions(sessionRows),
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
    listeners(({ actions }) => ({
        setDateFilter: () => {
            actions.reloadAll()
        },
        reloadAll: () => {
            actions.loadKPIs()
            actions.loadToolRows()
            actions.loadSessionRows()
            actions.loadHarnessRows()
            actions.loadActivityRows()
            actions.loadToolDailyRows()
        },
    })),
    actionToUrl(({ values }) => ({
        setDateFilter: () => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.dateFilter.dateFrom) {
                searchParams.date_from = values.dateFilter.dateFrom
            } else {
                delete searchParams.date_from
            }
            if (values.dateFilter.dateTo) {
                searchParams.date_to = values.dateFilter.dateTo
            } else {
                delete searchParams.date_to
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values, cache }) => ({
        [urls.mcpAnalyticsDashboard()]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo) {
                // setDateFilter's listener reloads everything.
                actions.setDateFilter(dateFrom, dateTo)
            } else if (!cache.hasLoaded) {
                // URL already matches state (e.g. default window) and afterMount deferred — load once here.
                actions.reloadAll()
            }
            cache.hasLoaded = true
        },
    })),
    afterMount(({ actions, cache }) => {
        // urlToAction owns the initial load whenever the dashboard URL carries filter
        // params; this is the fallback for a param-less mount (and off-route mounts in
        // tests, where urlToAction never fires). The cache.hasLoaded guard keeps a
        // deep-linked load from firing twice.
        const { searchParams } = router.values
        const hasUrlFilters = typeof searchParams.date_from === 'string' || typeof searchParams.date_to === 'string'
        if (!hasUrlFilters && !cache.hasLoaded) {
            cache.hasLoaded = true
            actions.reloadAll()
        }
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

// Pick at most one session per rule. Thresholds relax automatically when the
// data is small so something demo-worthy always shows.
export function pickNotableSessions(rows: SessionRow[]): NotableSession[] {
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

    // Top up to the target with the busiest sessions not already chosen, so the table reads as a
    // fuller list rather than a sparse handful.
    const byVolume = [...rows].sort((a, b) => b.tool_calls - a.tool_calls)
    for (const candidate of byVolume) {
        if (picked.length >= NOTABLE_SESSION_TARGET) {
            break
        }
        take('high_activity', 'High activity', candidate)
    }

    return picked
}
