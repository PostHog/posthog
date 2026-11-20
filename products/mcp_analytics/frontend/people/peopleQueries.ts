import { hogql } from 'lib/utils/hogql'

import { DateRange, HogQLQuery } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import {
    MCP_CLIENT_EXPR,
    MCP_HARNESS_EXPR,
    MCP_IS_ERROR_EXPR,
    MCP_MODEL_EXPR,
    MCP_TOOL_EXPR,
} from '../components/toolCallFeedQuery'
import type { MCPSharedQueryFilters } from '../mcpAnalyticsFiltersLogic'
import { withFilters } from '../tool-quality/toolReportQueries'

// Without identify the SDK sends the session ID, or "anonymous", as the distinct ID.
const IDENTIFIED = `distinct_id != 'anonymous'
    AND distinct_id != toString(properties.$session_id)
    AND distinct_id != coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))`
const SESSION = 'toString(properties.$session_id)'
const DURATION = 'toFloat(properties.$mcp_duration_ms)'
// ponytail: 200 rows and no paging, add paging when projects outgrow it.
const PEOPLE_LIMIT = 200

export interface PersonRow {
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

export function peopleQuery(dateRange: DateRange, filters: MCPSharedQueryFilters): HogQLQuery {
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
LIMIT ${hogql.raw(String(PEOPLE_LIMIT))}`,
        dateRange,
        filters
    )
}

export function toPersonRows(results: unknown[][] | undefined): PersonRow[] {
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

/** Calls, sessions, errors and p95 for one person, split into the selected period and the one before it. */
export function personTotalsQuery(
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

export function personSeriesQuery(
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

export type PersonTopDimension = 'tools' | 'harnesses' | 'models'

const DIMENSION_EXPR: Record<PersonTopDimension, string> = {
    tools: MCP_TOOL_EXPR,
    harnesses: MCP_HARNESS_EXPR,
    models: `coalesce(nullIf(${MCP_MODEL_EXPR}, ''), 'Unknown')`,
}

/** Rows of [label, calls, errors, error rate %], most called first. */
export function personTopQuery(
    distinctId: string,
    dimension: PersonTopDimension,
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

/** The person's newest calls, in the columns `toExampleCalls` reads, plus whether each failed. */
export function personRecentCallsQuery(
    distinctId: string,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    return withFilters(
        hogql`SELECT
    uuid,
    timestamp,
    ${hogql.raw(SESSION)} AS session_id,
    toString(properties.$mcp_intent) AS intent,
    ${hogql.raw(DURATION)} AS duration_ms,
    ${hogql.raw(MCP_CLIENT_EXPR)} AS client,
    coalesce(nullIf(toString(properties.$mcp_error_type), ''), 'Unknown') AS error_type,
    toString(properties.$mcp_error_message) AS error_message,
    ${hogql.raw(MCP_HARNESS_EXPR)} AS harness,
    ${hogql.raw(MCP_TOOL_EXPR)} AS tool,
    ${hogql.raw(MCP_IS_ERROR_EXPR)} AS is_error
FROM events
WHERE event = '$mcp_tool_call' AND distinct_id = ${distinctId} AND {filters}
ORDER BY timestamp DESC
LIMIT 10`,
        dateRange,
        filters
    )
}
