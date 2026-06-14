import { afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

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

// Raw HogQL result rows (positional columns), rendered by the tool detail tables.
export type ResultRows = unknown[][]

// Gap-fill the per-day rows into a continuous day axis (ClickHouse only returns days with data).
// Counts fill with 0; latency fills with NaN so the chart skips the point instead of dipping to 0.
function buildDailyChartData(rows: DailyToolStat[]): DailyChartData {
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

const NEW_SDK_SOURCE = 'posthog_mcp_analytics'

// HogQL expression that resolves to the *effective* tool name for new-SDK events:
// the inner tool when the call went through the single-exec wrapper, otherwise
// the directly-registered tool name. Use anywhere we need to filter/group by tool.
const EFFECTIVE_TOOL_HOGQL =
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))"

const NEW_SDK_FILTER = `properties.$mcp_source = '${NEW_SDK_SOURCE}'`

function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
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
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50_ms,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_ms,
    uniq(distinct_id) AS users,
    uniq(coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))) AS conversations
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND ${toolFilter}
`,
                    })) as HogQLQueryResponse
                    const row = (response.results ?? [])[0]
                    if (!row) {
                        return null
                    }
                    return {
                        calls: Number(row[0]) || 0,
                        errors: Number(row[1]) || 0,
                        p50_ms: row[2] == null ? null : Number(row[2]),
                        p95_ms: row[3] == null ? null : Number(row[3]),
                        users: Number(row[4]) || 0,
                        conversations: Number(row[5]) || 0,
                    }
                },
            },
        ],
        descriptions: [
            [] as DescriptionRevision[],
            {
                loadDescriptions: async (): Promise<DescriptionRevision[]> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    toString(properties.$mcp_tool_description) AS description,
    toString(max(timestamp)) AS last_seen
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND ${toolFilter}
    AND notEmpty(toString(properties.$mcp_tool_description))
GROUP BY description
ORDER BY last_seen DESC
LIMIT 5
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []).map((row) => ({
                        description: String(row[0] ?? ''),
                        last_seen: String(row[1] ?? ''),
                    }))
                },
            },
        ],
        intentCoverage: [
            null as IntentCoverage | null,
            {
                loadIntentCoverage: async (): Promise<IntentCoverage | null> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    countIf(notEmpty(toString(properties.$mcp_intent)) AND toString(properties.$mcp_intent) != '{}') AS with_intent,
    count() AS total
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND ${toolFilter}
`,
                    })) as HogQLQueryResponse
                    const row = (response.results ?? [])[0]
                    if (!row) {
                        return null
                    }
                    return { with_intent: Number(row[0]) || 0, total: Number(row[1]) || 0 }
                },
            },
        ],
        dailyStats: [
            [] as DailyToolStat[],
            {
                loadDailyStats: async (): Promise<DailyToolStat[]> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    toDate(timestamp) AS day,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95,
    uniq(distinct_id) AS users,
    uniq(coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))) AS sessions
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND ${toolFilter}
GROUP BY day
ORDER BY day
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []).map((r) => ({
                        day: String(r[0] ?? ''),
                        calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        p50: Number(r[3] ?? 0),
                        p95: Number(r[4] ?? 0),
                        users: Number(r[5] ?? 0),
                        sessions: Number(r[6] ?? 0),
                    }))
                },
            },
        ],
        failureRows: [
            [] as ResultRows,
            {
                loadFailureRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    substring(toString(properties.$exception_message), 1, 200) AS message,
    count() AS occurrences,
    max(timestamp) AS last_seen,
    arrayStringConcat(arraySort(arrayDistinct(groupArray(toString(properties.$mcp_client_name)))), ', ') AS harnesses
FROM events
WHERE event = '$exception'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND toString(properties.$mcp_tool_name) = '${escapeHogQLString(props.toolName)}'
    AND notEmpty(toString(properties.$exception_message))
GROUP BY message
ORDER BY occurrences DESC
LIMIT 20
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
                },
            },
        ],
        sampleIntentRows: [
            [] as ResultRows,
            {
                loadSampleIntentRows: async (): Promise<ResultRows> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    timestamp,
    toString(properties.$mcp_intent) AS intent,
    toString(properties.$mcp_intent_source) AS source,
    toString(properties.$mcp_client_name) AS harness
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND ${toolFilter}
    AND notEmpty(toString(properties.$mcp_intent))
    AND toString(properties.$mcp_intent) != '{}'
ORDER BY timestamp DESC
LIMIT 5
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
                },
            },
        ],
        neighborsBeforeRows: [
            [] as ResultRows,
            {
                loadNeighborsBeforeRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
WITH tool_calls AS (
    SELECT
        coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id)) AS conv_id,
        timestamp,
        ${EFFECTIVE_TOOL_HOGQL} AS tool
    FROM events
    WHERE event = 'mcp_tool_call'
        AND timestamp >= now() - INTERVAL 7 DAY
        AND ${NEW_SDK_FILTER}
        AND notEmpty(coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id)))
)
SELECT prev_tool AS tool, count() AS co_occurrences
FROM (
    SELECT
        conv_id,
        tool,
        lagInFrame(tool) OVER (PARTITION BY conv_id ORDER BY timestamp ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_tool
    FROM tool_calls
)
WHERE tool = '${escapeHogQLString(props.toolName)}' AND prev_tool IS NOT NULL AND prev_tool != '' AND prev_tool != tool
GROUP BY prev_tool
ORDER BY co_occurrences DESC
LIMIT 5
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
                },
            },
        ],
        neighborsAfterRows: [
            [] as ResultRows,
            {
                loadNeighborsAfterRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
WITH tool_calls AS (
    SELECT
        coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id)) AS conv_id,
        timestamp,
        ${EFFECTIVE_TOOL_HOGQL} AS tool
    FROM events
    WHERE event = 'mcp_tool_call'
        AND timestamp >= now() - INTERVAL 7 DAY
        AND ${NEW_SDK_FILTER}
        AND notEmpty(coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id)))
)
SELECT next_tool AS tool, count() AS co_occurrences
FROM (
    SELECT
        conv_id,
        tool,
        leadInFrame(tool) OVER (PARTITION BY conv_id ORDER BY timestamp ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS next_tool
    FROM tool_calls
)
WHERE tool = '${escapeHogQLString(props.toolName)}' AND next_tool IS NOT NULL AND next_tool != '' AND next_tool != tool
GROUP BY next_tool
ORDER BY co_occurrences DESC
LIMIT 5
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
                },
            },
        ],
        byHarnessRows: [
            [] as ResultRows,
            {
                loadByHarnessRows: async (): Promise<ResultRows> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    toString(properties.$mcp_client_name) AS harness,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    uniq(distinct_id) AS users
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND ${toolFilter}
    AND notEmpty(toString(properties.$mcp_client_name))
GROUP BY harness
ORDER BY calls DESC
LIMIT 10
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
                },
            },
        ],
        topUserRows: [
            [] as ResultRows,
            {
                loadTopUserRows: async (): Promise<ResultRows> => {
                    const toolFilter = `${EFFECTIVE_TOOL_HOGQL} = '${escapeHogQLString(props.toolName)}' AND ${NEW_SDK_FILTER}`
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    argMax(tuple(distinct_id, person.created_at, person.properties), timestamp) AS person,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    arrayStringConcat(arraySort(arrayDistinct(groupArray(toString(properties.$mcp_client_name)))), ', ') AS harnesses,
    max(timestamp) AS last_seen
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND ${toolFilter}
GROUP BY distinct_id
ORDER BY calls DESC
LIMIT 10
`,
                    })) as HogQLQueryResponse
                    return (response.results ?? []) as ResultRows
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
