// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/mcp_analytics/api'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpAnalyticsIntentClustersRecomputeSchema = () => z.object({})

const mcpAnalyticsIntentClustersRecompute = (): ToolBase<
    ReturnType<typeof McpAnalyticsIntentClustersRecomputeSchema>,
    unknown
> => ({
    name: 'mcp-analytics-intent-clusters-recompute',
    schema: McpAnalyticsIntentClustersRecomputeSchema(),
    handler: async (
        context: Context,
        _params: z.infer<ReturnType<typeof McpAnalyticsIntentClustersRecomputeSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/recompute/`,
        })
        return result
    },
})

const McpAnalyticsIntentClustersRetrieveSchema = () => {
    const McpAnalyticsIntentClustersRetrieveQueryParams = orvalSchemas.McpAnalyticsIntentClustersRetrieveQueryParams()
    return McpAnalyticsIntentClustersRetrieveQueryParams
}

const mcpAnalyticsIntentClustersRetrieve = (): ToolBase<
    ReturnType<typeof McpAnalyticsIntentClustersRetrieveSchema>,
    Schemas.MCPIntentClusterSnapshot[]
> => ({
    name: 'mcp-analytics-intent-clusters-retrieve',
    schema: McpAnalyticsIntentClustersRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpAnalyticsIntentClustersRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPIntentClusterSnapshot[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/`,
            query: {
                tool: params.tool,
            },
        })
        return result
    },
})

const McpAnalyticsSessionsGenerateIntentSchema = () => {
    const McpAnalyticsSessionsGenerateIntentParams = orvalSchemas.McpAnalyticsSessionsGenerateIntentParams()
    const McpAnalyticsSessionsGenerateIntentQueryParams = orvalSchemas.McpAnalyticsSessionsGenerateIntentQueryParams()
    return McpAnalyticsSessionsGenerateIntentParams.omit({ project_id: true }).extend(
        McpAnalyticsSessionsGenerateIntentQueryParams.shape
    )
}

const mcpAnalyticsSessionsGenerateIntent = (): ToolBase<
    ReturnType<typeof McpAnalyticsSessionsGenerateIntentSchema>,
    Schemas.MCPSessionIntent
> => ({
    name: 'mcp-analytics-sessions-generate-intent',
    schema: McpAnalyticsSessionsGenerateIntentSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpAnalyticsSessionsGenerateIntentSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPSessionIntent>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/generate_intent/`,
            query: {
                date_from: params.date_from,
            },
        })
        return result
    },
})

const McpAnalyticsSessionsListSchema = () => {
    const McpAnalyticsSessionsListQueryParams = orvalSchemas.McpAnalyticsSessionsListQueryParams()
    return McpAnalyticsSessionsListQueryParams
}

const mcpAnalyticsSessionsList = (): ToolBase<
    ReturnType<typeof McpAnalyticsSessionsListSchema>,
    WithPostHogUrl<Schemas.PaginatedMCPSessionList>
> => ({
    name: 'mcp-analytics-sessions-list',
    schema: McpAnalyticsSessionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpAnalyticsSessionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPSessionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                filter_test_accounts: params.filter_test_accounts,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                properties: params.properties,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/mcp-analytics')
    },
})

const McpAnalyticsSessionsToolCallsSchema = () => {
    const McpAnalyticsSessionsToolCallsParams = orvalSchemas.McpAnalyticsSessionsToolCallsParams()
    const McpAnalyticsSessionsToolCallsQueryParams = orvalSchemas.McpAnalyticsSessionsToolCallsQueryParams()
    return McpAnalyticsSessionsToolCallsParams.omit({ project_id: true }).extend(
        McpAnalyticsSessionsToolCallsQueryParams.shape
    )
}

const mcpAnalyticsSessionsToolCalls = (): ToolBase<
    ReturnType<typeof McpAnalyticsSessionsToolCallsSchema>,
    WithPostHogUrl<Schemas.PaginatedMCPToolCallList>
> => ({
    name: 'mcp-analytics-sessions-tool-calls',
    schema: McpAnalyticsSessionsToolCallsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpAnalyticsSessionsToolCallsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPToolCallList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/tool_calls/`,
            query: {
                date_from: params.date_from,
                filter_test_accounts: params.filter_test_accounts,
                limit: params.limit,
                offset: params.offset,
                properties: params.properties,
            },
        })
        return await withPostHogUrl(context, result, '/mcp-analytics')
    },
})

const McpMissingCapabilityReportSchema = () => {
    const McpAnalyticsMissingCapabilitiesCreateBody = orvalSchemas.McpAnalyticsMissingCapabilitiesCreateBody()
    return McpAnalyticsMissingCapabilitiesCreateBody.omit({
        mcp_client_name: true,
        mcp_client_version: true,
        mcp_protocol_version: true,
        mcp_transport: true,
        mcp_session_id: true,
        mcp_trace_id: true,
    })
}

const mcpMissingCapabilityReport = (): ToolBase<
    ReturnType<typeof McpMissingCapabilityReportSchema>,
    Schemas.MCPAnalyticsSubmission
> => ({
    name: 'mcp-missing-capability-report',
    schema: McpMissingCapabilityReportSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpMissingCapabilityReportSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.missing_capability !== undefined) {
            body['missing_capability'] = params.missing_capability
        }
        if (params.blocked !== undefined) {
            body['blocked'] = params.blocked
        }
        const result = await context.api.request<Schemas.MCPAnalyticsSubmission>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/missing_capabilities/`,
            body,
        })
        return result
    },
})

// --- Query wrapper schemas from schema.json ---

const DateRange = z.object({
    date_from: z
        .string()
        .nullable()
        .describe(
            'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
        )
        .optional(),
    date_to: z
        .string()
        .nullable()
        .describe(
            'End of the date range. Same format as date_from. Omit or null for "now". A calendar day without a time (2024-01-15) is inclusive: it rounds to the last moment of that day in the project timezone, unless explicitDate is set.'
        )
        .optional(),
    daysOfWeek: z
        .union([
            z.array(
                z.union([
                    z.literal(1),
                    z.literal(2),
                    z.literal(3),
                    z.literal(4),
                    z.literal(5),
                    z.literal(6),
                    z.literal(7),
                ])
            ),
            z.null(),
        ])
        .describe(
            'Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries.'
        )
        .optional(),
    excludeIncompletePeriods: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries.'
        )
        .default(false)
        .optional(),
    explicitDate: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        )
        .default(false)
        .optional(),
})

const PropertyOperator = z.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'starts_with',
    'not_starts_with',
    'ends_with',
    'not_ends_with',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

const PropertyFilterBaseValue = z.union([z.string(), z.number(), z.boolean()])

const PropertyFilterValue = z.union([PropertyFilterBaseValue, z.array(PropertyFilterBaseValue), z.null()])

const EventPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator.default('exact'),
    type: z.literal('event').describe('Event properties').default('event'),
    value: PropertyFilterValue.optional(),
})

const PersonPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('person').describe('Person properties').default('person'),
    value: PropertyFilterValue.optional(),
})

const SessionPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('session').default('session'),
    value: PropertyFilterValue.optional(),
})

const MCPAnalyticsPropertyFilter = z.union([EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter])

const MCPHarnessBreakdownQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPHarnessBreakdownQuery').default('MCPHarnessBreakdownQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('When set, scope to a single effective tool\'s new-SDK calls (the per-tool "By harness" table).')
        .optional(),
})

const MCPToolStatsQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolStatsQuery').default('MCPToolStatsQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const IntervalType = z.enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])

const MCPToolDailyStatsQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    interval: IntervalType.describe(
        'Bucket granularity for the series. The frontend passes getDefaultInterval so a sub-day window buckets by hour/minute instead of collapsing to a single day point. Defaults to day.'
    ).optional(),
    kind: z.literal('MCPToolDailyStatsQuery').default('MCPToolDailyStatsQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolFailuresQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolFailuresQuery').default('MCPToolFailuresQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolFailureOccurrencesQuery = z.object({
    dateRange: DateRange.optional(),
    errorStatus: z
        .string()
        .describe('When set, only events with this HTTP status match; when unset, only events without a status match.')
        .optional(),
    errorType: z
        .string()
        .describe('Raw $mcp_error_type bucket; "unknown" selects errored events without an error type.'),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolFailureOccurrencesQuery').default('MCPToolFailureOccurrencesQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolTopUsersQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolTopUsersQuery').default('MCPToolTopUsersQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolNeighborsQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolNeighborsQuery').default('MCPToolNeighborsQuery'),
    neighborDirection: z
        .enum(['before', 'after'])
        .describe('Whether to count tools called immediately before or after the target tool.'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolSampleIntentsQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolSampleIntentsQuery').default('MCPToolSampleIntentsQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolDescriptionsQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPToolDescriptionsQuery').default('MCPToolDescriptionsQuery'),
    properties: z.array(MCPAnalyticsPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const integer = z.coerce.number().int()

const MCPMissingCapabilitiesQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPMissingCapabilitiesQuery').default('MCPMissingCapabilitiesQuery'),
    limit: integer.describe('Page size; defaults to 100, capped at 500.').optional(),
    offset: integer
        .describe(
            "Reports to skip before returning results. Combine with limit to page through them; the response's has_next flag indicates whether more remain."
        )
        .optional(),
    search: z.string().describe('Case-insensitive substring match over the report text.').optional(),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-analytics-intent-clusters-recompute': mcpAnalyticsIntentClustersRecompute,
    'mcp-analytics-intent-clusters-retrieve': mcpAnalyticsIntentClustersRetrieve,
    'mcp-analytics-sessions-generate-intent': mcpAnalyticsSessionsGenerateIntent,
    'mcp-analytics-sessions-list': mcpAnalyticsSessionsList,
    'mcp-analytics-sessions-tool-calls': mcpAnalyticsSessionsToolCalls,
    'mcp-missing-capability-report': mcpMissingCapabilityReport,
    'query-mcp-harness-breakdown': createQueryWrapper({
        name: 'query-mcp-harness-breakdown',
        schema: MCPHarnessBreakdownQuery,
        kind: 'MCPHarnessBreakdownQuery',
    }),
    'query-mcp-tool-stats': createQueryWrapper({
        name: 'query-mcp-tool-stats',
        schema: MCPToolStatsQuery,
        kind: 'MCPToolStatsQuery',
    }),
    'query-mcp-tool-daily-stats': createQueryWrapper({
        name: 'query-mcp-tool-daily-stats',
        schema: MCPToolDailyStatsQuery,
        kind: 'MCPToolDailyStatsQuery',
    }),
    'query-mcp-tool-failures': createQueryWrapper({
        name: 'query-mcp-tool-failures',
        schema: MCPToolFailuresQuery,
        kind: 'MCPToolFailuresQuery',
    }),
    'query-mcp-tool-failure-occurrences': createQueryWrapper({
        name: 'query-mcp-tool-failure-occurrences',
        schema: MCPToolFailureOccurrencesQuery,
        kind: 'MCPToolFailureOccurrencesQuery',
    }),
    'query-mcp-tool-top-users': createQueryWrapper({
        name: 'query-mcp-tool-top-users',
        schema: MCPToolTopUsersQuery,
        kind: 'MCPToolTopUsersQuery',
    }),
    'query-mcp-tool-neighbors': createQueryWrapper({
        name: 'query-mcp-tool-neighbors',
        schema: MCPToolNeighborsQuery,
        kind: 'MCPToolNeighborsQuery',
    }),
    'query-mcp-tool-sample-intents': createQueryWrapper({
        name: 'query-mcp-tool-sample-intents',
        schema: MCPToolSampleIntentsQuery,
        kind: 'MCPToolSampleIntentsQuery',
    }),
    'query-mcp-tool-descriptions': createQueryWrapper({
        name: 'query-mcp-tool-descriptions',
        schema: MCPToolDescriptionsQuery,
        kind: 'MCPToolDescriptionsQuery',
    }),
    'query-mcp-missing-capabilities': createQueryWrapper({
        name: 'query-mcp-missing-capabilities',
        schema: MCPMissingCapabilitiesQuery,
        kind: 'MCPMissingCapabilitiesQuery',
    }),
}
