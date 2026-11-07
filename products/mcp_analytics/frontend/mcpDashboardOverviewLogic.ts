import {
    BreakPointFunction,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { getDefaultInterval } from 'lib/utils/dateFilters'
import {
    type ComparisonWindow,
    buildBucketKeys,
    buildComparisonWindow,
    lastBucketIsInProgress,
    normalizeBucket,
} from 'lib/utils/timeBuckets'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    HogQLFilters,
    HogQLQueryResponse,
    MCPHarnessBreakdownItem,
    MCPModelBreakdownItem,
    MCPProtocolVersionBreakdownItem,
    MCPToolCallBreakdownItem,
    MCPToolCallsAndErrorsItem,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, IntervalType } from '~/types'

import { mcpClusteringLogic } from './clustering/mcpClusteringLogic'
import type { MCPIntentClusterApi } from './generated/api.schemas'
import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'
import { mcpToolReportUrl } from './mcpAnalyticsToolQualityLogic'

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }

// KPI tiles compare the selected window against the immediately preceding window
// of equal length. The current/previous split is applied in `buildKPIs` against
// the time buckets, so the query only needs the doubled date range. `__BUCKET__`
// is replaced with a dateTrunc at the active interval at call time.
//
// Key on the canonical event only — also matching the legacy `mcp_tool_call` alias would double-count.
const KPI_QUERY = `
SELECT
    __BUCKET__ AS bucket,
    countDistinctIf($session_id, $session_id != '') AS sessions,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY bucket
ORDER BY bucket
`

// Distinct MCP users for the "Users" tile — how many distinct people made tool calls.
// Counted over the doubled window like the KPI query, then split into the selected period
// and its equal-length predecessor with a single conditional uniq so the comparison is a
// true distinct-user count (summing per-bucket distinct users would over-count anyone
// active on more than one day). `__CUR_START__` is the selected-period boundary, injected
// as a timezone-aware toDateTime at call time.
// Users are counted by distinct_id, not person_id. HogQL resolves person_id through a join
// over every person override of the project, and on large projects that join runs out of
// memory. A person with several distinct_ids counts once per distinct_id.
const PERIOD_TOTALS_QUERY = `
SELECT
    uniqIf(distinct_id, timestamp >= __CUR_START__) AS current_users,
    uniqIf(distinct_id, timestamp < __CUR_START__) AS prior_users,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp >= __CUR_START__)) AS current_p95,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp < __CUR_START__)) AS prior_p95
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
`

// Per-session rollup powering the Notable sessions block. The selector
// applies fixed rules over this set; no per-rule SQL.
const SESSION_ROWS_QUERY = `
SELECT
    $session_id AS session_id,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    uniq(toString(properties.$mcp_tool_name)) AS distinct_tools,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$mcp_tool_call'
    AND $session_id != ''
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY session_id
HAVING tool_calls >= 1
ORDER BY tool_calls DESC
LIMIT 500
`

// Mirrors MCPToolQualityRowsQueryRunner (products/mcp_analytics/backend/hogql_queries/tool_quality_tables.py)
// for the compact reliability matrix on the overview. Limited columns + 50 rows.
const TOOL_ROWS_QUERY = `
SELECT
    toString(properties.$mcp_tool_name) AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY tool
ORDER BY total_calls DESC
LIMIT 50
`

// The harness breakdown is resolved server-side by the MCPHarnessBreakdownQuery
// runner (products/mcp_analytics/backend/hogql_queries/harness_breakdown.py) — the
// single source of truth for client → harness labelling — so the tile reads typed,
// already-bucketed rows rather than re-deriving the labels in the browser.

// The `__BUCKET__` expression the KPI query is built with. toString() is load-bearing: a bare
// dateTrunc returns a typed DateTime that the query API serializes with the project's UTC offset
// attached (2026-07-21T00:00:00-07:00), which the client then reads back as an instant and
// converts, shifting every bucket away from the wall-clock keys it joins and compares against.
// Rendering it server-side leaves a plain string with nothing left to reinterpret, matching the
// backend runners (dashboard_series.py, tool_quality_tables.py, tool_tables.py).
export const bucketExpr = (interval: IntervalType): string => `toString(dateTrunc('${interval}', timestamp))`

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
    sparklineLabels: string[]
    goodDirection: 'up' | 'down'
}

export interface KPIData {
    sessions: KPIMetric
    toolCalls: KPIMetric
    errorRatePct: KPIMetric
    p95LatencyMs: KPIMetric
}

// Window-level figures that can't be summed from per-bucket rows: distinct users and a percentile.
export interface PeriodTotals {
    users: KPIMetric
    p95LatencyMs: KPIMetric
}

export interface ToolRow {
    tool: string
    total_calls: number
    errors: number
    error_rate_pct: number
    p95_duration_ms: number
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
}

export function toHarnessRow(item: MCPHarnessBreakdownItem): HarnessRow {
    return {
        category: item.harness,
        total_calls: item.total_calls,
        errors: item.errors,
        error_rate_pct: item.error_rate_pct,
        sessions: item.sessions,
    }
}

export interface ModelRow {
    model: string
    total_calls: number
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

// Calls the busiest session needs before it is worth flagging. Absolute rather than relative to the
// median, because the query returns the 500 busiest sessions, so the median of what we get is not the
// account's median.
const MIN_OUTLIER_CALLS = 5

// Below this, a session is an ordinary task rather than an exploration.
const MIN_JOURNEY_TOOLS = 4

export interface NotableSession {
    rule: NotableRule
    label: string
    session: SessionRow
}

const EMPTY_METRIC: KPIMetric = {
    value: 0,
    previousValue: 0,
    deltaPct: null,
    sparkline: [],
    sparklineLabels: [],
    goodDirection: 'up',
}
const EMPTY_PERIOD_TOTALS: PeriodTotals = {
    users: { ...EMPTY_METRIC, goodDirection: 'up' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}
const EMPTY_KPIS: KPIData = {
    sessions: { ...EMPTY_METRIC, goodDirection: 'up' },
    toolCalls: { ...EMPTY_METRIC, goodDirection: 'up' },
    errorRatePct: { ...EMPTY_METRIC, goodDirection: 'down' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}

// Keep the stacked bar legible: only the busiest tools get their own segment; the long tail is
// folded into a single "Other" series so the chart can't sprout dozens of repeating-colour bands.
const TOOL_SERIES_LIMIT = 8

// Pivot flat (day, tool, calls) rows into a label array + one data series per tool, tools ordered
// by total volume (biggest first) so the stack and legend read consistently. When `bucketKeys` is
// supplied the labels span the full selected window (zero-filling empty buckets) so the x-axis
// matches the date range instead of collapsing to the days that happened to have calls; without it
// the labels fall back to the days present in the rows (a plain pivot, used in tests).
export function buildToolDailySeries(rows: ToolDailyRow[], bucketKeys?: string[]): ToolDailySeries {
    const days = bucketKeys ?? [...new Set(rows.map((r) => r.day))].sort()
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

// Window resolution, bucket keys, the comparison window, and the bucket-key format are shared with the
// tab and detail surfaces. See lib/utils/timeBuckets.

// Project the daily success/error rows onto the full set of buckets, defaulting empty buckets to 0.
export function buildDailyActivity(rows: ActivityRow[], bucketKeys: string[]): DailyActivity {
    const byDay = new Map(rows.map((r) => [r.day, r]))
    return {
        labels: bucketKeys,
        successes: bucketKeys.map((k) => byDay.get(k)?.successes ?? 0),
        errors: bucketKeys.map((k) => byDay.get(k)?.errors ?? 0),
    }
}

// Merge the dashboard's active filters with a doubled comparison window's date range.
// Shared by the KPI and Users loaders so both tiles are scoped to the exact same window —
// the tile-parity the reload test asserts. Keep the two loaders reading from here so the
// window/filter plumbing can't drift between them.
function kpiWindowFilters(queryFilters: HogQLFilters, kpiWindow: ComparisonWindow): HogQLFilters {
    return { ...queryFilters, dateRange: { date_from: kpiWindow.dateFrom, date_to: kpiWindow.dateTo } }
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

// A tool with a handful of calls swings to 100% on one failure, so ranking needs a minimum sample.
export const MIN_CALLS_TO_RANK_ERRORS = 20

export function rankToolsByErrorRate(rows: ToolRow[]): ToolRow[] {
    return rows
        .filter((r) => r.total_calls >= MIN_CALLS_TO_RANK_ERRORS)
        .sort((a, b) => b.error_rate_pct - a.error_rate_pct)
}

export function rankedToolsEmptyMessage(rows: ToolRow[]): string | undefined {
    return rows.length > 0 ? `No tool has ${MIN_CALLS_TO_RANK_ERRORS} or more calls in this date range yet.` : undefined
}

// Buckets at or after `currentStartBucket` belong to the selected window; the
// rest are the equal-length window immediately before it.
export function buildKPIs(rows: BucketRow[], currentStartBucket: string): KPIData {
    const current = rows.filter((r) => r.bucket >= currentStartBucket).sort((a, b) => a.bucket.localeCompare(b.bucket))
    const previous = rows.filter((r) => r.bucket < currentStartBucket)

    const errorRate = (rows_: BucketRow[]): number => {
        const calls = rows_.reduce((acc, r) => acc + r.tool_calls, 0)
        return calls ? (rows_.reduce((acc, r) => acc + r.errors, 0) / calls) * 100 : 0
    }

    const curSessions = current.reduce((acc, r) => acc + r.sessions, 0)
    const curCalls = current.reduce((acc, r) => acc + r.tool_calls, 0)

    const prevSessions = previous.reduce((acc, r) => acc + r.sessions, 0)
    const prevCalls = previous.reduce((acc, r) => acc + r.tool_calls, 0)

    const curErrorRate = errorRate(current)
    const prevErrorRate = errorRate(previous)
    const sparklineLabels = current.map((r) => r.bucket)

    return {
        sessions: {
            value: curSessions,
            previousValue: prevSessions,
            deltaPct: deltaPct(curSessions, prevSessions),
            sparkline: current.map((r) => r.sessions),
            sparklineLabels,
            goodDirection: 'up',
        },
        toolCalls: {
            value: curCalls,
            previousValue: prevCalls,
            deltaPct: deltaPct(curCalls, prevCalls),
            sparkline: current.map((r) => r.tool_calls),
            sparklineLabels,
            goodDirection: 'up',
        },
        errorRatePct: {
            value: curErrorRate,
            previousValue: prevErrorRate,
            deltaPct: deltaPct(curErrorRate, prevErrorRate),
            sparkline: current.map((r) => (r.tool_calls ? (r.errors / r.tool_calls) * 100 : 0)),
            sparklineLabels,
            goodDirection: 'down',
        },
        // The headline value comes from PeriodTotals; a period p95 can't be built from bucket p95s.
        p95LatencyMs: {
            ...EMPTY_METRIC,
            sparkline: current.map((r) => r.p95),
            sparklineLabels,
            goodDirection: 'down',
        },
    }
}

export type FailedLoads = Partial<
    Record<
        | 'kpis'
        | 'periodTotals'
        | 'toolRows'
        | 'sessionRows'
        | 'harnessRows'
        | 'modelRows'
        | 'protocolVersionRows'
        | 'activityRows'
        | 'toolDailyRows',
        boolean
    >
>

// Drops a request superseded by a newer one, even when it fails, so a late failure can't mark the
// newer result as failed.
async function queryLatest<T>(query: Parameters<typeof api.query>[0], breakpoint: BreakPointFunction): Promise<T> {
    try {
        return (await api.query(query)) as T
    } finally {
        breakpoint()
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicValues {
    sharedQueryFilters: MCPSharedQueryFilters // mcpAnalyticsFiltersLogic
    clusters: readonly MCPIntentClusterApi[] // mcpClusteringLogic
    hasSnapshot: boolean // mcpClusteringLogic
    totalClusterCount: number // mcpClusteringLogic
    currentTeamId: number | null // teamLogic
    timezone: string // teamLogic
    activityIncompleteTail: boolean
    activityRows: ActivityRow[]
    activityRowsLoading: boolean
    bucketKeys: string[]
    canShowFeedback: boolean
    dailyActivity: DailyActivity
    dashboardLoading: boolean
    dateFilter: DateFilter
    failedLoads: FailedLoads
    feedbackContextKey: string
    feedbackLoadFailed: boolean
    harnessRows: HarnessRow[]
    harnessRowsLoading: boolean
    hasFilterInteraction: boolean
    hasModelData: boolean
    hasProtocolVersionData: boolean
    headlineKpis: KPIData
    intentClusterCount: KPIMetric
    interval: IntervalType
    kpiIncompleteTail: boolean
    kpis: KPIData
    kpisLoading: boolean
    modelRows: ModelRow[]
    modelRowsLoading: boolean
    notableSessions: NotableSession[]
    periodTotals: PeriodTotals
    periodTotalsLoading: boolean
    protocolVersionRows: MCPProtocolVersionBreakdownItem[]
    protocolVersionRowsLoading: boolean
    queryFilters: HogQLFilters
    sessionRows: SessionRow[]
    sessionRowsLoading: boolean
    toolDailyRows: ToolDailyRow[]
    toolDailyRowsLoading: boolean
    toolDailySeries: ToolDailySeries
    toolRows: ToolRow[]
    toolRowsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicActions {
    hydrateFilters: (
        filterTestAccountsOverride: boolean | null,
        propertyFilters: AnyPropertyFilter[]
    ) => {
        filterTestAccountsOverride: boolean | null
        propertyFilters: AnyPropertyFilter[]
    } // mcpAnalyticsFiltersLogic
    setFilterTestAccounts: (filterTestAccounts: boolean | null) => {
        filterTestAccounts: boolean | null
    } // mcpAnalyticsFiltersLogic
    setPropertyFilters: (properties: AnyPropertyFilter[]) => {
        properties: AnyPropertyFilter[]
    } // mcpAnalyticsFiltersLogic
    loadActivityRows: (_: void) => void
    loadActivityRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadActivityRowsSuccess: (
        activityRows: ActivityRow[],
        payload?: void
    ) => {
        activityRows: ActivityRow[]
        payload?: void
    }
    loadHarnessRows: (_: void) => void
    loadHarnessRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHarnessRowsSuccess: (
        harnessRows: HarnessRow[],
        payload?: void
    ) => {
        harnessRows: HarnessRow[]
        payload?: void
    }
    loadKPIs: (_: void) => void
    loadKPIsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadKPIsSuccess: (
        kpis: KPIData,
        payload?: void
    ) => {
        kpis: KPIData
        payload?: void
    }
    loadModelRows: (_: void) => void
    loadModelRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadModelRowsSuccess: (
        modelRows: ModelRow[],
        payload?: void
    ) => {
        modelRows: ModelRow[]
        payload?: void
    }
    loadPeriodTotals: (_: void) => void
    loadPeriodTotalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPeriodTotalsSuccess: (
        periodTotals: PeriodTotals,
        payload?: void
    ) => {
        periodTotals: PeriodTotals
        payload?: void
    }
    loadProtocolVersionRows: (_: void) => void
    loadProtocolVersionRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadProtocolVersionRowsSuccess: (
        protocolVersionRows: MCPProtocolVersionBreakdownItem[],
        payload?: void
    ) => {
        protocolVersionRows: MCPProtocolVersionBreakdownItem[]
        payload?: void
    }
    loadSessionRows: (_: void) => void
    loadSessionRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSessionRowsSuccess: (
        sessionRows: {
            distinct_tools: number
            duration_seconds: number
            error_rate_pct: number
            errors: number
            last_seen: string
            session_id: string
            tool_calls: number
        }[],
        payload?: void
    ) => {
        sessionRows: {
            distinct_tools: number
            duration_seconds: number
            error_rate_pct: number
            errors: number
            last_seen: string
            session_id: string
            tool_calls: number
        }[]
        payload?: void
    }
    loadToolDailyRows: (_: void) => void
    loadToolDailyRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadToolDailyRowsSuccess: (
        toolDailyRows: ToolDailyRow[],
        payload?: void
    ) => {
        toolDailyRows: ToolDailyRow[]
        payload?: void
    }
    loadToolRows: (_: void) => void
    loadToolRowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadToolRowsSuccess: (
        toolRows: {
            error_rate_pct: number
            errors: number
            p95_duration_ms: number
            tool: string
            total_calls: number
        }[],
        payload?: void
    ) => {
        toolRows: {
            error_rate_pct: number
            errors: number
            p95_duration_ms: number
            tool: string
            total_calls: number
        }[]
        payload?: void
    }
    markFilterInteraction: () => {
        value: true
    }
    openToolReport: (tool: string) => {
        tool: string
    }
    reloadAll: () => {
        value: true
    }
    setDateFilter: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        dashboardLoading: (
            kpisLoading: boolean,
            periodTotalsLoading: boolean,
            toolRowsLoading: boolean,
            sessionRowsLoading: boolean,
            harnessRowsLoading: boolean,
            modelRowsLoading: boolean,
            protocolVersionRowsLoading: boolean,
            activityRowsLoading: boolean,
            toolDailyRowsLoading: boolean
        ) => boolean
        feedbackLoadFailed: (
            failedLoads: Partial<
                Record<
                    | 'activityRows'
                    | 'harnessRows'
                    | 'kpis'
                    | 'modelRows'
                    | 'periodTotals'
                    | 'protocolVersionRows'
                    | 'sessionRows'
                    | 'toolDailyRows'
                    | 'toolRows',
                    boolean
                >
            >
        ) => boolean
        canShowFeedback: (
            hasFilterInteraction: boolean,
            dashboardLoading: boolean,
            feedbackLoadFailed: boolean,
            kpis: KPIData
        ) => boolean
        feedbackContextKey: (currentTeamId: number | null) => string
        queryFilters: (
            dateFilter: DateFilter,
            sharedQueryFilters: Required<Pick<HogQLFilters, 'filterTestAccounts' | 'properties'>>
        ) => HogQLFilters
        interval: (dateFilter: DateFilter) => IntervalType
        bucketKeys: (dateFilter: DateFilter, timezone: string, interval: IntervalType) => string[]
        activityIncompleteTail: (bucketKeys: string[], timezone: string, interval: IntervalType) => boolean
        headlineKpis: (kpis: KPIData, periodTotals: PeriodTotals) => KPIData
        kpiIncompleteTail: (kpis: KPIData, timezone: string, interval: IntervalType) => boolean
        dailyActivity: (activityRows: ActivityRow[], bucketKeys: string[]) => DailyActivity
        toolDailySeries: (toolDailyRows: ToolDailyRow[], bucketKeys: string[]) => ToolDailySeries
        notableSessions: (sessionRows: SessionRow[]) => NotableSession[]
        hasModelData: (modelRows: ModelRow[]) => boolean
        hasProtocolVersionData: (protocolVersionRows: MCPProtocolVersionBreakdownItem[]) => boolean
        intentClusterCount: (totalClusterCount: number) => KPIMetric
    }
}

export type mcpDashboardOverviewLogicType = MakeLogicType<
    mcpDashboardOverviewLogicValues,
    mcpDashboardOverviewLogicActions,
    Record<string, any>,
    mcpDashboardOverviewLogicMeta
>

export const mcpDashboardOverviewLogic = kea<mcpDashboardOverviewLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpDashboardOverviewLogic']),
    connect(() => ({
        values: [
            mcpClusteringLogic,
            ['clusters', 'hasSnapshot', 'totalClusterCount'],
            teamLogic,
            ['timezone', 'currentTeamId'],
            mcpAnalyticsFiltersLogic,
            ['queryFilters as sharedQueryFilters'],
        ],
        actions: [mcpAnalyticsFiltersLogic, ['hydrateFilters', 'setFilterTestAccounts', 'setPropertyFilters']],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        reloadAll: true,
        markFilterInteraction: true,
        openToolReport: (tool: string) => ({ tool }),
    }),
    reducers({
        hasFilterInteraction: [false, { markFilterInteraction: () => true }],
        failedLoads: [
            {} as FailedLoads,
            {
                loadKPIs: (state) => ({ ...state, kpis: false }),
                loadKPIsFailure: (state) => ({ ...state, kpis: true }),
                loadPeriodTotals: (state) => ({ ...state, periodTotals: false }),
                loadPeriodTotalsFailure: (state) => ({ ...state, periodTotals: true }),
                loadToolRows: (state) => ({ ...state, toolRows: false }),
                loadToolRowsFailure: (state) => ({ ...state, toolRows: true }),
                loadSessionRows: (state) => ({ ...state, sessionRows: false }),
                loadSessionRowsFailure: (state) => ({ ...state, sessionRows: true }),
                loadHarnessRows: (state) => ({ ...state, harnessRows: false }),
                loadHarnessRowsFailure: (state) => ({ ...state, harnessRows: true }),
                loadModelRows: (state) => ({ ...state, modelRows: false }),
                loadModelRowsFailure: (state) => ({ ...state, modelRows: true }),
                loadProtocolVersionRows: (state) => ({ ...state, protocolVersionRows: false }),
                loadProtocolVersionRowsFailure: (state) => ({ ...state, protocolVersionRows: true }),
                loadActivityRows: (state) => ({ ...state, activityRows: false }),
                loadActivityRowsFailure: (state) => ({ ...state, activityRows: true }),
                loadToolDailyRows: (state) => ({ ...state, toolDailyRows: false }),
                loadToolDailyRowsFailure: (state) => ({ ...state, toolDailyRows: true }),
            },
        ],
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
                    const { interval } = values
                    const kpiWindow = buildComparisonWindow(
                        values.dateFilter.dateFrom,
                        values.dateFilter.dateTo,
                        values.timezone,
                        interval
                    )
                    const response = await queryLatest<HogQLQueryResponse>(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: KPI_QUERY.replace('__BUCKET__', bucketExpr(interval)),
                            filters: kpiWindowFilters(values.queryFilters, kpiWindow),
                        },
                        breakpoint
                    )
                    const rows = parseRows((response?.results as unknown[][]) ?? [])
                    return buildKPIs(rows, kpiWindow.currentStartBucket)
                },
            },
        ],
        periodTotals: [
            EMPTY_PERIOD_TOTALS,
            {
                loadPeriodTotals: async (_: void, breakpoint): Promise<PeriodTotals> => {
                    const { interval, timezone } = values
                    const kpiWindow = buildComparisonWindow(
                        values.dateFilter.dateFrom,
                        values.dateFilter.dateTo,
                        timezone,
                        interval
                    )
                    // Split the doubled window at the selected period's start. currentStartBucket is
                    // interval-aligned (buildComparisonWindow truncates to the bucket start), so comparing the raw
                    // `timestamp` against toDateTime(bucket, tz) lands on the same instant as the KPI
                    // tiles' dateTrunc bucket-string split — keeping this count consistent with them.
                    // (For rolling sub-day ranges the two halves can differ by up to two intervals, the
                    // same bounded skew the KPI tiles already carry; splitting on the raw start instead
                    // would equalize the halves but desync Users from the other tiles, so don't.)
                    const curStart = `toDateTime('${kpiWindow.currentStartBucket}', '${timezone}')`
                    const response = await queryLatest<HogQLQueryResponse>(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: PERIOD_TOTALS_QUERY.replace(/__CUR_START__/g, curStart),
                            filters: kpiWindowFilters(values.queryFilters, kpiWindow),
                        },
                        breakpoint
                    )
                    const row = (response?.results as unknown[][])?.[0] ?? []
                    const metric = (
                        value: number,
                        previousValue: number,
                        goodDirection: KPIMetric['goodDirection']
                    ): KPIMetric => ({
                        value,
                        previousValue,
                        deltaPct: deltaPct(value, previousValue),
                        sparkline: [],
                        sparklineLabels: [],
                        goodDirection,
                    })
                    return {
                        users: metric(Number(row[0] ?? 0), Number(row[1] ?? 0), 'up'),
                        p95LatencyMs: metric(Number(row[2] ?? 0), Number(row[3] ?? 0), 'down'),
                    }
                },
            },
        ],
        toolRows: [
            [] as ToolRow[],
            {
                loadToolRows: async (_: void, breakpoint) => {
                    const response = await queryLatest<HogQLQueryResponse>(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: TOOL_ROWS_QUERY,
                            filters: values.queryFilters,
                        },
                        breakpoint
                    )
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
                    const response = await queryLatest<HogQLQueryResponse>(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: SESSION_ROWS_QUERY,
                            filters: values.queryFilters,
                        },
                        breakpoint
                    )
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
        harnessRows: [
            [] as HarnessRow[],
            {
                loadHarnessRows: async (_: void, breakpoint) => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = await queryLatest<{ results?: MCPHarnessBreakdownItem[] }>(
                        {
                            kind: NodeKind.MCPHarnessBreakdownQuery,
                            dateRange,
                            properties,
                            filterTestAccounts,
                        },
                        breakpoint
                    )
                    return (response?.results ?? []).map(toHarnessRow)
                },
            },
        ],
        modelRows: [
            [] as ModelRow[],
            {
                loadModelRows: async (_: void, breakpoint): Promise<ModelRow[]> => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = await queryLatest<{ results?: MCPModelBreakdownItem[] }>(
                        {
                            kind: NodeKind.MCPModelBreakdownQuery,
                            dateRange,
                            properties,
                            filterTestAccounts,
                        },
                        breakpoint
                    )
                    return response?.results ?? []
                },
            },
        ],
        protocolVersionRows: [
            [] as MCPProtocolVersionBreakdownItem[],
            {
                loadProtocolVersionRows: async (_: void, breakpoint): Promise<MCPProtocolVersionBreakdownItem[]> => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = await queryLatest<{ results?: MCPProtocolVersionBreakdownItem[] }>(
                        {
                            kind: NodeKind.MCPProtocolVersionBreakdownQuery,
                            dateRange,
                            properties,
                            filterTestAccounts,
                        },
                        breakpoint
                    )
                    return response?.results ?? []
                },
            },
        ],
        activityRows: [
            [] as ActivityRow[],
            {
                loadActivityRows: async (_: void, breakpoint): Promise<ActivityRow[]> => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = await queryLatest<{ results?: MCPToolCallsAndErrorsItem[] }>(
                        {
                            kind: NodeKind.MCPToolCallsAndErrorsQuery,
                            dateRange,
                            properties,
                            filterTestAccounts,
                            interval: values.interval,
                        },
                        breakpoint
                    )
                    return (response?.results ?? []).map((r) => ({
                        day: normalizeBucket(r.bucket),
                        successes: r.successes,
                        errors: r.errors,
                    }))
                },
            },
        ],
        toolDailyRows: [
            [] as ToolDailyRow[],
            {
                loadToolDailyRows: async (_: void, breakpoint): Promise<ToolDailyRow[]> => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = await queryLatest<{ results?: MCPToolCallBreakdownItem[] }>(
                        {
                            kind: NodeKind.MCPToolCallBreakdownQuery,
                            dateRange,
                            properties,
                            filterTestAccounts,
                            interval: values.interval,
                        },
                        breakpoint
                    )
                    return (response?.results ?? []).map((r) => ({
                        day: normalizeBucket(r.bucket),
                        tool: r.tool,
                        calls: r.calls,
                    }))
                },
            },
        ],
    })),
    selectors({
        dashboardLoading: [
            (s) => [
                s.kpisLoading,
                s.periodTotalsLoading,
                s.toolRowsLoading,
                s.sessionRowsLoading,
                s.harnessRowsLoading,
                s.modelRowsLoading,
                s.protocolVersionRowsLoading,
                s.activityRowsLoading,
                s.toolDailyRowsLoading,
            ],
            (...loading: boolean[]): boolean => loading.some(Boolean),
        ],
        feedbackLoadFailed: [
            (s) => [s.failedLoads],
            (failedLoads: FailedLoads): boolean => Object.values(failedLoads).some(Boolean),
        ],
        canShowFeedback: [
            (s) => [s.hasFilterInteraction, s.dashboardLoading, s.feedbackLoadFailed, s.kpis],
            (interacted: boolean, loading: boolean, failed: boolean, kpis: KPIData): boolean =>
                interacted && !loading && !failed && kpis.toolCalls.value > 0,
        ],
        feedbackContextKey: [(s) => [s.currentTeamId], (teamId: number | null): string => String(teamId ?? undefined)],
        queryFilters: [
            (s) => [s.dateFilter, s.sharedQueryFilters],
            (dateFilter: DateFilter, sharedQueryFilters: MCPSharedQueryFilters): HogQLFilters => ({
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                ...sharedQueryFilters,
            }),
        ],
        interval: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): IntervalType => getDefaultInterval(dateFilter.dateFrom, dateFilter.dateTo),
        ],
        bucketKeys: [
            (s) => [s.dateFilter, s.timezone, s.interval],
            (dateFilter: DateFilter, timezone: string, interval: IntervalType): string[] =>
                buildBucketKeys(dateFilter.dateFrom, dateFilter.dateTo, timezone, interval),
        ],
        // Whether the activity chart's final bucket is the current, still-running interval — the
        // chart dashes that segment so a partial period doesn't read as a drop in tool calls.
        activityIncompleteTail: [
            (s) => [s.bucketKeys, s.timezone, s.interval],
            (bucketKeys: string[], timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(bucketKeys, timezone, interval),
        ],
        // Read off the KPI sparkline's own labels, not `bucketKeys`: the sparkline is not zero-filled,
        // so on a day with no calls yet its last point is yesterday, which is settled.
        headlineKpis: [
            (s) => [s.kpis, s.periodTotals],
            (kpis: KPIData, periodTotals: PeriodTotals): KPIData => ({
                ...kpis,
                p95LatencyMs: {
                    ...kpis.p95LatencyMs,
                    ...periodTotals.p95LatencyMs,
                    sparkline: kpis.p95LatencyMs.sparkline,
                    sparklineLabels: kpis.p95LatencyMs.sparklineLabels,
                },
            }),
        ],
        kpiIncompleteTail: [
            (s) => [s.kpis, s.timezone, s.interval],
            (kpis: KPIData, timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(kpis.sessions.sparklineLabels, timezone, interval),
        ],
        dailyActivity: [
            (s) => [s.activityRows, s.bucketKeys],
            (rows: ActivityRow[], bucketKeys: string[]): DailyActivity => buildDailyActivity(rows, bucketKeys),
        ],
        toolDailySeries: [
            (s) => [s.toolDailyRows, s.bucketKeys],
            (rows: ToolDailyRow[], bucketKeys: string[]): ToolDailySeries => buildToolDailySeries(rows, bucketKeys),
        ],
        notableSessions: [
            (s) => [s.sessionRows],
            (sessionRows: SessionRow[]): NotableSession[] => pickNotableSessions(sessionRows),
        ],
        hasModelData: [
            (s) => [s.modelRows],
            (modelRows: ModelRow[]): boolean => modelRows.some((row) => row.total_calls > 0),
        ],
        hasProtocolVersionData: [
            (s) => [s.protocolVersionRows],
            (protocolVersionRows: MCPProtocolVersionBreakdownItem[]): boolean => protocolVersionRows.length > 0,
        ],
        intentClusterCount: [
            // The snapshot only stores the top clusters by call volume — report
            // the run's true count, not the length of the truncated list.
            (s) => [s.totalClusterCount],
            (totalClusterCount: number): KPIMetric => ({
                value: totalClusterCount,
                previousValue: 0,
                deltaPct: null,
                sparkline: [],
                sparklineLabels: [],
                goodDirection: 'up',
            }),
        ],
    }),
    listeners(({ actions, values }) => ({
        setDateFilter: () => {
            actions.reloadAll()
        },
        openToolReport: ({ tool }) => {
            router.actions.push(mcpToolReportUrl(tool, values.dateFilter))
        },
        setFilterTestAccounts: () => {
            actions.markFilterInteraction()
            actions.reloadAll()
        },
        setPropertyFilters: () => {
            actions.markFilterInteraction()
            actions.reloadAll()
        },
        hydrateFilters: () => {
            const { searchParams } = router.values.currentLocation
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom === values.dateFilter.dateFrom && dateTo === values.dateFilter.dateTo) {
                actions.reloadAll()
            }
        },
        reloadAll: () => {
            actions.loadKPIs()
            actions.loadPeriodTotals()
            actions.loadToolRows()
            actions.loadSessionRows()
            actions.loadHarnessRows()
            actions.loadModelRows()
            actions.loadProtocolVersionRows()
            actions.loadActivityRows()
            actions.loadToolDailyRows()
        },
    })),
    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
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
        }
        return {
            setDateFilter: syncUrl,
        }
    }),
    // The shared property and test-account filters hydrate from the same URL in
    // mcpAnalyticsFiltersLogic, which mounts first (connected), so a deep-linked load below
    // already sees them.
    urlToAction(({ actions, values, cache }) => ({
        [urls.mcpAnalyticsDashboard()]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            const dateChanged = dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo
            if (dateChanged) {
                actions.setDateFilter(dateFrom, dateTo)
            }
            // URL already matches state (e.g. default filters) and afterMount deferred — load once.
            if (!dateChanged && !cache.hasLoaded) {
                actions.reloadAll()
            }
            cache.hasLoaded = true
        },
    })),
    afterMount(({ actions, cache }) => {
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

// Pick at most one session per rule, so every row has a reason to be there. Deliberately returns
// short, or empty, when nothing qualifies.
export function pickNotableSessions(rows: SessionRow[]): NotableSession[] {
    if (rows.length === 0) {
        return []
    }

    const medianCalls = median(rows.map((r) => r.tool_calls))
    const medianDuration = median(rows.map((r) => r.duration_seconds))
    const busyThreshold = Math.max(medianCalls, 3)
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
    const highVolume = rows.filter((r) => r.tool_calls >= busyThreshold && r.error_rate_pct > 0)
    take(
        'worst_error_rate',
        'Worst error rate at high volume',
        [...highVolume].sort((a, b) => b.error_rate_pct - a.error_rate_pct || b.tool_calls - a.tool_calls)[0]
    )

    // 2. All-fail session — error_rate_pct === 100 AND tool_calls >= 3
    const allFail = rows.filter((r) => r.error_rate_pct >= 100 && r.tool_calls >= 3)
    take(
        'all_fail',
        'Every call failed, likely an auth scope issue',
        [...allFail].sort((a, b) => b.tool_calls - a.tool_calls)[0]
    )

    // 3. Most exploratory — highest distinct_tools count, among sessions that are journeys at all
    const journeys = rows.filter((r) => r.distinct_tools >= MIN_JOURNEY_TOOLS)
    take(
        'most_exploratory',
        'Most exploratory journey',
        [...journeys].sort((a, b) => b.distinct_tools - a.distinct_tools || b.tool_calls - a.tool_calls)[0]
    )

    // 4. Exemplar — zero errors, above-median calls, faster than median duration
    const exemplars = rows.filter(
        (r) => r.error_rate_pct === 0 && r.tool_calls >= busyThreshold && r.duration_seconds <= medianDuration
    )
    take('exemplar', 'Concise success', [...exemplars].sort((a, b) => b.tool_calls - a.tool_calls)[0])

    // 5. High activity — the busiest session, once it is busy enough to be worth reading. Being the
    // largest of a small set is not notable: on a quiet account that can be a single tool call.
    const busiest = [...rows].sort((a, b) => b.tool_calls - a.tool_calls)[0]
    if (busiest && busiest.tool_calls >= MIN_OUTLIER_CALLS) {
        take('high_activity', 'High activity', busiest)
    }

    return picked
}
