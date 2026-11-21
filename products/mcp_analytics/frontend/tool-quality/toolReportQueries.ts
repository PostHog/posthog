import { hogql } from 'lib/utils/hogql'

import { DateRange, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import {
    MCP_CLIENT_EXPR,
    MCP_IS_ERROR_EXPR as IS_ERROR,
    MCP_MODEL_EXPR,
    MCP_TOOL_EXPR,
} from '../components/toolCallFeedQuery'
import type { MCPSharedQueryFilters } from '../mcpAnalyticsFiltersLogic'

const EXAMPLES_PER_LIST = 3

export type ExampleKind = 'errored' | 'slow' | 'succeeded'

export interface ExampleCall {
    uuid: string
    timestamp: string
    /** Empty for a call made without a session, which has nothing to open. */
    sessionId: string
    intent: string
    durationMs: number | null
    client: string
    errorType: string
    errorMessage: string
    harness: string
    /** Set where calls of several tools share a list. */
    tool?: string
}

export type ToolExamples = Record<ExampleKind, ExampleCall[]>

export function withFilters(query: string, dateRange: DateRange, filters: MCPSharedQueryFilters): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query,
        filters: { dateRange, properties: filters.properties, filterTestAccounts: filters.filterTestAccounts },
    }
}

const EXAMPLE_ORDER: Record<ExampleKind, { where: string; tail: string }> = {
    errored: {
        where: IS_ERROR,
        tail: `ORDER BY timestamp DESC LIMIT ${EXAMPLES_PER_LIST}`,
    },
    slow: {
        where: 'isNotNull(toFloat(properties.$mcp_duration_ms))',
        tail: `ORDER BY duration_ms DESC LIMIT ${EXAMPLES_PER_LIST}`,
    },
    // Calls that recorded an intent first, so the list shows what agents meant to do.
    succeeded: {
        where: `NOT ${IS_ERROR}`,
        tail: `ORDER BY intent != '' DESC, timestamp DESC LIMIT ${EXAMPLES_PER_LIST}`,
    },
}

export function toolExamplesQuery(
    kind: ExampleKind,
    toolName: string,
    dateRange: DateRange,
    filters: MCPSharedQueryFilters
): HogQLQuery {
    const { where, tail } = EXAMPLE_ORDER[kind]
    return withFilters(
        hogql`SELECT
    uuid,
    timestamp,
    toString(properties.$session_id) AS session_id,
    toString(properties.$mcp_intent) AS intent,
    toFloat(properties.$mcp_duration_ms) AS duration_ms,
    ${hogql.raw(MCP_CLIENT_EXPR)} AS client,
    coalesce(nullIf(toString(properties.$mcp_error_type), ''), 'Unknown') AS error_type,
    toString(properties.$mcp_error_message) AS error_message,
    toString(properties.$virt_mcp_harness) AS harness
FROM events
WHERE event = '$mcp_tool_call' AND ${hogql.raw(MCP_TOOL_EXPR)} = ${toolName} AND {filters} AND ${hogql.raw(where)}
${hogql.raw(tail)}`,
        dateRange,
        filters
    )
}

export function toExampleCalls(results: unknown[][] | undefined): ExampleCall[] {
    return (results ?? []).map(
        ([uuid, timestamp, sessionId, intent, durationMs, client, errorType, errorMessage, harness, tool]) => ({
            uuid: String(uuid ?? ''),
            timestamp: String(timestamp ?? ''),
            sessionId: String(sessionId ?? ''),
            intent: String(intent ?? ''),
            durationMs: durationMs === null || durationMs === undefined ? null : Number(durationMs),
            client: String(client ?? ''),
            errorType: String(errorType ?? ''),
            errorMessage: String(errorMessage ?? ''),
            harness: String(harness ?? ''),
            tool: tool === undefined ? undefined : String(tool),
        })
    )
}

export function toolTopModelsQuery(toolName: string, dateRange: DateRange, filters: MCPSharedQueryFilters): HogQLQuery {
    return withFilters(
        hogql`SELECT
    coalesce(nullIf(${hogql.raw(MCP_MODEL_EXPR)}, ''), 'Unknown') AS model,
    count() AS calls,
    countIf(${hogql.raw(IS_ERROR)}) AS errors,
    uniq(distinct_id) AS users
FROM events
WHERE event = '$mcp_tool_call' AND ${hogql.raw(MCP_TOOL_EXPR)} = ${toolName} AND {filters}
GROUP BY model
ORDER BY calls DESC
LIMIT 20`,
        dateRange,
        filters
    )
}

const JOURNEY_DEPTH = 4
const JOURNEY_PATHS = 10

/** One path through a session's first tools, shaped like an intent cluster's journey path. */
export interface ToolJourneyPath {
    /** Always JOURNEY_DEPTH long. null where the session ended before that step. */
    steps: (string | null)[]
    outcome: 'completed' | 'error'
    count: number
}

export interface ToolJourney {
    paths: ToolJourneyPath[]
    /** Every session that called the tool, not just the top paths, so shares stay true. */
    totalSessions: number
    errorSessions: number
}

/** Top first-tool paths of sessions that called the tool; one failed call errors the session. */
export function toolJourneyQuery(toolName: string, dateRange: DateRange, filters: MCPSharedQueryFilters): HogQLQuery {
    return withFilters(
        hogql`SELECT steps, outcome, sessions, sum(sessions) OVER () AS total_sessions,
    sumIf(sessions, outcome = 'error') OVER () AS error_sessions
FROM (
    SELECT steps, outcome, count() AS sessions
    FROM (
        SELECT
            arrayMap(x -> tupleElement(x, 2), arraySlice(arraySort(groupArray(tuple(timestamp, tool))), 1, ${JOURNEY_DEPTH})) AS steps,
            if(countIf(is_error) > 0, 'error', 'completed') AS outcome
        FROM (
            SELECT
                toString(properties.$session_id) AS session_id,
                ${hogql.raw(MCP_TOOL_EXPR)} AS tool,
                timestamp,
                ${hogql.raw(IS_ERROR)} AS is_error
            FROM events
            WHERE event = '$mcp_tool_call' AND {filters} AND notEmpty(toString(properties.$session_id))
        )
        GROUP BY session_id
        HAVING has(groupArray(tool), ${toolName})
    )
    GROUP BY steps, outcome
)
ORDER BY sessions DESC
LIMIT ${JOURNEY_PATHS}`,
        dateRange,
        filters
    )
}

export function toToolJourney(results: unknown[][] | undefined): ToolJourney {
    const rows = results ?? []
    return {
        paths: rows.map(([steps, outcome, count]) => {
            const named = Array.isArray(steps) ? steps.map((step) => (step ? String(step) : null)) : []
            return {
                steps: [...named, ...Array(Math.max(0, JOURNEY_DEPTH - named.length)).fill(null)].slice(
                    0,
                    JOURNEY_DEPTH
                ),
                outcome: outcome === 'error' ? 'error' : 'completed',
                count: Number(count ?? 0),
            }
        }),
        totalSessions: Number(rows[0]?.[3] ?? 0),
        errorSessions: Number(rows[0]?.[4] ?? 0),
    }
}
