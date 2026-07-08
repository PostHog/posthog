import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { dayjs, dayjsAdd, dayjsSubtract } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLFilters, HogQLQueryResponse, MCPHarnessBreakdownItem, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, IntervalType, TeamType } from '~/types'

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
// true distinct-person count (summing per-bucket distinct users would over-count anyone
// active on more than one day). `__CUR_START__` is the selected-period boundary, injected
// as a timezone-aware toDateTime at call time.
const USERS_QUERY = `
SELECT
    uniqIf(person_id, timestamp >= __CUR_START__) AS current_users,
    uniqIf(person_id, timestamp < __CUR_START__) AS prior_users
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

// Daily success/error split powering the activity time-series bar chart.
const ACTIVITY_QUERY = `
SELECT
    __BUCKET__ AS day,
    countIf(NOT toBool(properties.$mcp_is_error)) AS successes,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = '$mcp_tool_call'
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
WHERE event = '$mcp_tool_call'
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

// Truncate to the start of an interval bucket the same way ClickHouse's dateTrunc does, so the keys
// we generate line up with the query's bucket strings. dayjs' startOf covers minute/hour/day/month;
// only 'week' differs — dateTrunc('week') is ISO (Monday-start) while dayjs defaults to Sunday.
function startOfBucket(d: dayjs.Dayjs, interval: IntervalType): dayjs.Dayjs {
    if (interval === 'week') {
        const day = d.day() // 0 = Sunday … 6 = Saturday
        return d.startOf('day').subtract((day + 6) % 7, 'day')
    }
    return d.startOf(interval)
}

// The one format for bucket keys — must match ClickHouse dateTrunc's DateTime output so the
// zero-fill join and the in-progress-tail comparison line up. Change it here, nowhere else.
const BUCKET_FORMAT = 'YYYY-MM-DD HH:mm:ss'

// Every bucket key across the resolved window [start, end] at the active interval, formatted to
// match dateTrunc's DateTime output ('YYYY-MM-DD HH:mm:ss'). The activity and tool-usage series are
// zero-filled against these so the x-axis spans the whole selected range instead of clipping to the
// buckets that happened to have events.
export function buildBucketKeys(dateFilter: DateFilter, timezone: string, interval: IntervalType): string[] {
    const { start, end } = resolveWindow(dateFilter, timezone)
    const last = startOfBucket(end, interval).valueOf()
    const keys: string[] = []
    let cursor = startOfBucket(start, interval)
    // Bounded dashboard windows keep this small; the cap is just a guard against a pathological range.
    for (let i = 0; cursor.valueOf() <= last && i < 100000; i++) {
        keys.push(cursor.format(BUCKET_FORMAT))
        cursor = dayjsAdd(cursor, 1, interval)
    }
    return keys
}

// True when the final bucket is the current, still-running interval (open-ended window), so the
// chart can dash that segment as "in progress" rather than letting the partial period read as data
// loss. Needs ≥2 buckets to have a segment to dash; `now` is injectable so the logic stays testable.
export function lastBucketIsInProgress(
    bucketKeys: string[],
    timezone: string,
    interval: IntervalType,
    now: dayjs.Dayjs = dayjs()
): boolean {
    if (bucketKeys.length < 2) {
        return false
    }
    const currentBucket = startOfBucket(now.tz(timezone), interval).format(BUCKET_FORMAT)
    return bucketKeys[bucketKeys.length - 1] === currentBucket
}

export function normalizeBucket(raw: unknown, timezone: string): string {
    const s = String(raw ?? '')
    return s ? dayjs(s).tz(timezone).format(BUCKET_FORMAT) : ''
}

// Project the daily success/error rows onto the full set of buckets, defaulting empty buckets to 0.
export function buildDailyActivity(rows: ActivityRow[], bucketKeys: string[]): DailyActivity {
    const byDay = new Map(rows.map((r) => [r.day, r]))
    return {
        labels: bucketKeys,
        successes: bucketKeys.map((k) => byDay.get(k)?.successes ?? 0),
        errors: bucketKeys.map((k) => byDay.get(k)?.errors ?? 0),
    }
}

export interface KpiWindow {
    dateFrom: string
    dateTo: string
    currentStartBucket: string
}

// Extend the resolved window back by an equal number of `interval` buckets so a
// single query returns both the selected period and its prior period.
// `currentStartBucket` is the cutoff `buildKPIs` splits on — formatted to match
// dateTrunc's DateTime output.
export function buildKpiWindow(dateFilter: DateFilter, timezone: string, interval: IntervalType): KpiWindow {
    const { start, end } = resolveWindow(dateFilter, timezone)
    // The selected period covers the inclusive buckets [start, end] — one more than
    // end.diff(start). Step the prior window back by that same count so the two
    // halves of the comparison span an equal number of buckets.
    const selectedBuckets = Math.max(1, end.diff(start, interval) + 1)
    const priorStart = dayjsSubtract(start, selectedBuckets, interval)
    return {
        dateFrom: priorStart.toISOString(),
        dateTo: end.toISOString(),
        currentStartBucket: start.startOf(interval).format(BUCKET_FORMAT),
    }
}

// Merge the dashboard's active filters with a doubled comparison window's date range.
// Shared by the KPI and Users loaders so both tiles are scoped to the exact same window —
// the tile-parity the reload test asserts. Keep the two loaders reading from here so the
// window/filter plumbing can't drift between them.
function kpiWindowFilters(queryFilters: HogQLFilters, kpiWindow: KpiWindow): HogQLFilters {
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
        values: [mcpClusteringLogic, ['clusters', 'hasSnapshot'], teamLogic, ['timezone', 'currentTeam']],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setFilterTestAccounts: (filterTestAccounts: boolean | null) => ({ filterTestAccounts }),
        setPropertyFilters: (properties: AnyPropertyFilter[]) => ({ properties }),
        reloadAll: true,
    }),
    reducers({
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
        // null until the user toggles — the effective value falls back to the team's
        // test_account_filters_default_checked setting (see the filterTestAccounts selector).
        filterTestAccountsOverride: [
            null as boolean | null,
            {
                setFilterTestAccounts: (_, { filterTestAccounts }): boolean | null => filterTestAccounts,
            },
        ],
        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { properties }): AnyPropertyFilter[] => properties,
            },
        ],
    }),
    loaders(({ values }) => ({
        kpis: [
            EMPTY_KPIS,
            {
                loadKPIs: async (_: void, breakpoint) => {
                    const { interval } = values
                    const kpiWindow = buildKpiWindow(values.dateFilter, values.timezone, interval)
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: KPI_QUERY.replace('__BUCKET__', `dateTrunc('${interval}', timestamp)`),
                        filters: kpiWindowFilters(values.queryFilters, kpiWindow),
                    })) as HogQLQueryResponse
                    breakpoint()
                    const rows = parseRows((response?.results as unknown[][]) ?? [])
                    return buildKPIs(rows, kpiWindow.currentStartBucket)
                },
            },
        ],
        users: [
            EMPTY_METRIC,
            {
                loadUsers: async (_: void, breakpoint): Promise<KPIMetric> => {
                    const { interval, timezone } = values
                    const kpiWindow = buildKpiWindow(values.dateFilter, timezone, interval)
                    // Split the doubled window at the selected period's start. currentStartBucket is
                    // interval-aligned (buildKpiWindow → start.startOf(interval)), so comparing the raw
                    // `timestamp` against toDateTime(bucket, tz) lands on the same instant as the KPI
                    // tiles' dateTrunc bucket-string split — keeping this count consistent with them.
                    // (For rolling sub-day ranges the two halves can differ by up to one interval, the
                    // same bounded skew the KPI tiles already carry; splitting on the raw start instead
                    // would equalize the halves but desync Users from the other tiles, so don't.)
                    const curStart = `toDateTime('${kpiWindow.currentStartBucket}', '${timezone}')`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: USERS_QUERY.replace(/__CUR_START__/g, curStart),
                        filters: kpiWindowFilters(values.queryFilters, kpiWindow),
                    })) as HogQLQueryResponse
                    breakpoint()
                    const row = (response?.results as unknown[][])?.[0] ?? []
                    const value = Number(row[0] ?? 0)
                    const previousValue = Number(row[1] ?? 0)
                    return {
                        value,
                        previousValue,
                        deltaPct: deltaPct(value, previousValue),
                        // No sparkline: the headline is a window-level distinct count, not a per-bucket series.
                        sparkline: [],
                        goodDirection: 'up',
                    }
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
        harnessRows: [
            [] as HarnessRow[],
            {
                loadHarnessRows: async (_: void, breakpoint) => {
                    const { dateRange, properties, filterTestAccounts } = values.queryFilters
                    const response = (await api.query({
                        kind: NodeKind.MCPHarnessBreakdownQuery,
                        dateRange,
                        properties,
                        filterTestAccounts,
                    })) as { results?: MCPHarnessBreakdownItem[] }
                    breakpoint()
                    return (response?.results ?? []).map((r) => ({
                        category: r.harness,
                        total_calls: r.total_calls,
                        errors: r.errors,
                        error_rate_pct: r.error_rate_pct,
                        sessions: r.sessions,
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
                        query: ACTIVITY_QUERY.replace('__BUCKET__', `dateTrunc('${values.interval}', timestamp)`),
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        day: normalizeBucket(r[0], values.timezone),
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
                        query: TOOL_DAILY_QUERY.replace('__BUCKET__', `dateTrunc('${values.interval}', timestamp)`),
                        filters: values.queryFilters,
                    })) as HogQLQueryResponse
                    breakpoint()
                    const raw = (response?.results as unknown[][]) ?? []
                    return raw.map((r) => ({
                        day: normalizeBucket(r[0], values.timezone),
                        tool: String(r[1] ?? ''),
                        calls: Number(r[2] ?? 0),
                    }))
                },
            },
        ],
    })),
    selectors({
        // Effective toggle state: the user's explicit override, else the team's default.
        filterTestAccounts: [
            (s) => [s.filterTestAccountsOverride, s.currentTeam],
            (override: boolean | null, currentTeam: TeamType | null): boolean =>
                override ?? !!currentTeam?.test_account_filters_default_checked,
        ],
        queryFilters: [
            (s) => [s.dateFilter, s.filterTestAccounts, s.propertyFilters],
            (
                dateFilter: DateFilter,
                filterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): HogQLFilters => ({
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                filterTestAccounts,
                // Drop incomplete picker rows and any malformed URL-hydrated entries before they fan out to every tile.
                properties: propertyFilters.filter(isValidPropertyFilter),
            }),
        ],
        interval: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): IntervalType => getDefaultInterval(dateFilter.dateFrom, dateFilter.dateTo),
        ],
        bucketKeys: [
            (s) => [s.dateFilter, s.timezone, s.interval],
            (dateFilter: DateFilter, timezone: string, interval: IntervalType): string[] =>
                buildBucketKeys(dateFilter, timezone, interval),
        ],
        // Whether the activity chart's final bucket is the current, still-running interval — the
        // chart dashes that segment so a partial period doesn't read as a drop in tool calls.
        activityIncompleteTail: [
            (s) => [s.bucketKeys, s.timezone, s.interval],
            (bucketKeys: string[], timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(bucketKeys, timezone, interval),
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
        setFilterTestAccounts: () => {
            actions.reloadAll()
        },
        setPropertyFilters: () => {
            actions.reloadAll()
        },
        reloadAll: () => {
            actions.loadKPIs()
            actions.loadUsers()
            actions.loadToolRows()
            actions.loadSessionRows()
            actions.loadHarnessRows()
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
            // Absent param = follow the team default; an explicit override (incl. false) persists.
            if (values.filterTestAccountsOverride === null) {
                delete searchParams.filter_test_accounts
            } else {
                searchParams.filter_test_accounts = values.filterTestAccountsOverride
            }
            if (values.propertyFilters.length > 0) {
                searchParams.properties = values.propertyFilters
            } else {
                delete searchParams.properties
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setDateFilter: syncUrl,
            setFilterTestAccounts: syncUrl,
            setPropertyFilters: syncUrl,
        }
    }),
    urlToAction(({ actions, values, cache }) => ({
        [urls.mcpAnalyticsDashboard()]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            // Absent param leaves the override null (effective value follows the team default).
            const rawFilter = searchParams.filter_test_accounts
            const filterOverride = rawFilter === undefined ? null : rawFilter === true || rawFilter === 'true'
            const properties = Array.isArray(searchParams.properties) ? searchParams.properties : []
            const dateChanged = dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo
            const filterChanged = filterOverride !== values.filterTestAccountsOverride
            const propertiesChanged = JSON.stringify(properties) !== JSON.stringify(values.propertyFilters)
            // setDateFilter / setFilterTestAccounts / setPropertyFilters each reload via their listeners.
            if (dateChanged) {
                actions.setDateFilter(dateFrom, dateTo)
            }
            if (filterChanged) {
                actions.setFilterTestAccounts(filterOverride)
            }
            if (propertiesChanged) {
                actions.setPropertyFilters(properties)
            }
            // URL already matches state (e.g. default filters) and afterMount deferred — load once.
            if (!dateChanged && !filterChanged && !propertiesChanged && !cache.hasLoaded) {
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
        const hasUrlFilters =
            typeof searchParams.date_from === 'string' ||
            typeof searchParams.date_to === 'string' ||
            typeof searchParams.filter_test_accounts !== 'undefined' ||
            Array.isArray(searchParams.properties)
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
