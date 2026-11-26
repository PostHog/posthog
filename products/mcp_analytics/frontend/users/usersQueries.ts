import { hogql } from 'lib/utils/hogql'

import { DateRange, HogQLQuery } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { MCP_HARNESS_EXPR, MCP_IS_ERROR_EXPR, MCP_MODEL_EXPR, MCP_TOOL_EXPR } from '../components/toolCallFeedQuery'
import type { MCPSharedQueryFilters } from '../mcpAnalyticsFiltersLogic'
import { withFilters } from '../tool-quality/toolReportQueries'

// Without identify the SDK sends the session ID, or "anonymous", as the distinct ID.
const IDENTIFIED = `distinct_id != 'anonymous'
    AND distinct_id != toString(properties.$session_id)
    AND distinct_id != coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))`
const SESSION = 'toString(properties.$session_id)'
const DURATION = 'toFloat(properties.$mcp_duration_ms)'
// ponytail: 200 rows and no paging, add paging when projects outgrow it.
const USERS_LIMIT = 200

export interface UserRow {
    distinctId: string
    label: string
    calls: number
    sessions: number
    errors: number
    p95Ms: number | null
    lastSeen: string
    topTool: string
    topHarness: string
}

export function usersQuery(dateRange: DateRange, filters: MCPSharedQueryFilters): HogQLQuery {
    return withFilters(
        hogql`SELECT
    distinct_id,
    any(coalesce(nullIf(toString(person.properties.email), ''), distinct_id)) AS label,
    count() AS calls,
    uniq(${hogql.raw(SESSION)}) AS sessions,
    countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}) AS errors,
    quantile(0.95)(${hogql.raw(DURATION)}) AS p95_ms,
    max(timestamp) AS last_seen,
    topK(1)(${hogql.raw(MCP_TOOL_EXPR)})[1] AS top_tool,
    topK(1)(${hogql.raw(MCP_HARNESS_EXPR)})[1] AS top_harness
FROM events
WHERE event = '$mcp_tool_call' AND {filters} AND ${hogql.raw(IDENTIFIED)}
GROUP BY distinct_id
ORDER BY calls DESC
LIMIT ${hogql.raw(String(USERS_LIMIT))}`,
        dateRange,
        filters
    )
}

export function toUserRows(results: unknown[][] | undefined): UserRow[] {
    return (results ?? []).map(
        ([distinctId, label, calls, sessions, errors, p95Ms, lastSeen, topTool, topHarness]) => ({
            distinctId: String(distinctId ?? ''),
            label: String(label ?? distinctId ?? ''),
            calls: Number(calls ?? 0),
            sessions: Number(sessions ?? 0),
            errors: Number(errors ?? 0),
            p95Ms: p95Ms === null || p95Ms === undefined || Number.isNaN(Number(p95Ms)) ? null : Number(p95Ms),
            lastSeen: String(lastSeen ?? ''),
            topTool: String(topTool ?? ''),
            topHarness: String(topHarness ?? ''),
        })
    )
}

/** Calls, sessions, errors and p95 for one user, split into the selected period and the one before it. */
export function userTotalsQuery(
    distinctId: string,
    currentStart: string,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    return withFilters(
        hogql`SELECT
    timestamp >= toDateTime(${currentStart}) AS is_current,
    count(),
    uniq(${hogql.raw(SESSION)}),
    countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}),
    quantile(0.95)(${hogql.raw(DURATION)})
FROM events
WHERE event = '$mcp_tool_call' AND distinct_id = ${distinctId} AND {filters}
GROUP BY is_current`,
        dateRange,
        filters
    )
}

export function userSeriesQuery(
    distinctId: string,
    interval: IntervalType,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    return withFilters(
        hogql`SELECT
    toString(dateTrunc(${interval}, timestamp)) AS bucket,
    count(),
    uniq(${hogql.raw(SESSION)}),
    countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}),
    quantile(0.95)(${hogql.raw(DURATION)})
FROM events
WHERE event = '$mcp_tool_call' AND distinct_id = ${distinctId} AND {filters}
GROUP BY bucket
ORDER BY bucket`,
        dateRange,
        filters
    )
}

export type UserTopDimension = 'tools' | 'harnesses' | 'models'

const DIMENSION_EXPR: Record<UserTopDimension, string> = {
    tools: MCP_TOOL_EXPR,
    harnesses: MCP_HARNESS_EXPR,
    models: `coalesce(nullIf(${MCP_MODEL_EXPR}, ''), 'Unknown')`,
}

/** Rows of [label, calls, errors, error rate %], most called first. */
export function userTopQuery(
    distinctId: string,
    dimension: UserTopDimension,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    return withFilters(
        hogql`SELECT
    ${hogql.raw(DIMENSION_EXPR[dimension])} AS label,
    count() AS calls,
    countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}) AS errors,
    round(countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}) * 100 / count(), 1) AS error_rate_pct
FROM events
WHERE event = '$mcp_tool_call' AND distinct_id = ${distinctId} AND {filters}
GROUP BY label
ORDER BY calls DESC
LIMIT 50`,
        dateRange,
        filters
    )
}

/** The user's newest sessions, with each one's calls, errors, harness, first intent and top tools. */
export function userRecentSessionsQuery(
    distinctId: string,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    return withFilters(
        hogql`SELECT
    ${hogql.raw(SESSION)} AS session_id,
    min(timestamp) AS started,
    max(timestamp) AS ended,
    count() AS calls,
    countIf(${hogql.raw(MCP_IS_ERROR_EXPR)}) AS errors,
    argMin(${hogql.raw(MCP_HARNESS_EXPR)}, timestamp) AS harness,
    argMinIf(toString(properties.$mcp_intent), timestamp, toString(properties.$mcp_intent) != '') AS intent,
    topK(3)(${hogql.raw(MCP_TOOL_EXPR)}) AS tools
FROM events
WHERE event = '$mcp_tool_call' AND distinct_id = ${distinctId} AND ${hogql.raw(SESSION)} != '' AND {filters}
GROUP BY session_id
ORDER BY started DESC
LIMIT 10`,
        dateRange,
        filters
    )
}
