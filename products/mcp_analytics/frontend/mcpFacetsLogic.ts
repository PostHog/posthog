import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { MCP_HARNESS_EXPR, MCP_IS_ERROR_EXPR, MCP_MODEL_EXPR, MCP_TOOL_EXPR } from './components/toolCallFeedQuery'

export interface McpFacetOption {
    value: string
    calls: number
}

export interface McpFacets {
    tools: McpFacetOption[]
    categories: McpFacetOption[]
    errorTypes: McpFacetOption[]
    /** Each tool's first call in the last 90 days, which the New tools filter compares to the date range. */
    toolFirstSeen: Record<string, string>
    harnesses: McpFacetOption[]
    models: McpFacetOption[]
    /** Each tool's p95 duration in ms, which the Activity tab's "Slow" filter compares a call against. */
    toolP95: Record<string, number>
    /** The p95 duration in ms across all calls, the Sessions tab's "Slow" threshold. */
    p95: number | null
    feedbackSessions: string[]
}

// ponytail: a fixed 30-day window, not each page's date range; scope it if the option lists drift from the data.
function facetQuery(expr: string, withP95 = false, where = 'true'): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query: `SELECT ${expr} AS value, count() AS calls${withP95 ? ', quantile(0.95)(toFloat(properties.$mcp_duration_ms))' : ''}
            FROM events
            WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY AND ${where}
            GROUP BY value
            HAVING notEmpty(toString(value))
            ORDER BY calls DESC
            LIMIT 200`,
    }
}

const TOOL_FIRST_SEEN_QUERY: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `SELECT ${MCP_TOOL_EXPR} AS tool, min(timestamp) AS first_seen
        FROM events
        WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 90 DAY
        GROUP BY tool
        HAVING notEmpty(toString(tool))
        LIMIT 1000`,
}

// ponytail: capped at 5000 sessions over 90 days; push it into the endpoints as a subquery if teams outgrow that.
const FEEDBACK_SESSIONS_QUERY: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `SELECT DISTINCT toString(properties.$session_id) AS session_id
        FROM events
        WHERE event IN ('$mcp_feedback', '$mcp_missing_capability')
            AND timestamp >= now() - INTERVAL 90 DAY
            AND notEmpty(session_id)
        LIMIT 5000`,
}

const OVERALL_P95_QUERY: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `SELECT quantile(0.95)(toFloat(properties.$mcp_duration_ms))
        FROM events
        WHERE event = '$mcp_tool_call' AND timestamp >= now() - INTERVAL 30 DAY`,
}

export const mcpFacetsLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'mcpFacetsLogic']),
    loaders({
        facets: [
            null as McpFacets | null,
            {
                loadFacets: async () => {
                    const [tools, categories, harnesses, models, overall, errorTypes, firstSeen, feedback] =
                        await Promise.all(
                            [
                                facetQuery(MCP_TOOL_EXPR, true),
                                facetQuery('toString(properties.$mcp_tool_category)'),
                                facetQuery(MCP_HARNESS_EXPR),
                                facetQuery(MCP_MODEL_EXPR),
                                OVERALL_P95_QUERY,
                                facetQuery('toString(properties.$mcp_error_type)', false, MCP_IS_ERROR_EXPR),
                                TOOL_FIRST_SEEN_QUERY,
                                FEEDBACK_SESSIONS_QUERY,
                            ].map((query) => api.query(query))
                        )
                    const toOptions = (response: { results?: any[][] }): McpFacetOption[] =>
                        (response.results ?? []).map(([value, calls]) => ({
                            value: String(value),
                            calls: Number(calls),
                        }))
                    return {
                        tools: toOptions(tools),
                        categories: toOptions(categories),
                        errorTypes: toOptions(errorTypes),
                        toolFirstSeen: Object.fromEntries(
                            (firstSeen.results ?? []).map(([tool, seen]: any[]) => [String(tool), String(seen)])
                        ),
                        harnesses: toOptions(harnesses),
                        models: toOptions(models),
                        toolP95: Object.fromEntries(
                            (tools.results ?? []).map(([value, , p95]: any[]) => [String(value), Number(p95)])
                        ),
                        p95: Number(overall.results?.[0]?.[0]) || null,
                        feedbackSessions: (feedback.results ?? []).map(([sessionId]: any[]) => String(sessionId)),
                    }
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadFacets()
    }),
])
