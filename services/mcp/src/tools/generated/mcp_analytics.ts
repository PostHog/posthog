// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    McpAnalyticsFeedbackCreateBody,
    McpAnalyticsMissingCapabilitiesCreateBody,
    McpAnalyticsSessionsGenerateIntentParams,
    McpAnalyticsSessionsGenerateIntentQueryParams,
    McpAnalyticsSessionsListQueryParams,
    McpAnalyticsSessionsToolCallsParams,
    McpAnalyticsSessionsToolCallsQueryParams,
} from '@/generated/mcp_analytics/api'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpAnalyticsIntentClustersRecomputeSchema = z.object({})

const mcpAnalyticsIntentClustersRecompute = (): ToolBase<
    typeof McpAnalyticsIntentClustersRecomputeSchema,
    unknown
> => ({
    name: 'mcp-analytics-intent-clusters-recompute',
    schema: McpAnalyticsIntentClustersRecomputeSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsIntentClustersRecomputeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/recompute/`,
        })
        return result
    },
})

const McpAnalyticsIntentClustersRetrieveSchema = z.object({})

const mcpAnalyticsIntentClustersRetrieve = (): ToolBase<
    typeof McpAnalyticsIntentClustersRetrieveSchema,
    Schemas.MCPIntentClusterSnapshot[]
> => ({
    name: 'mcp-analytics-intent-clusters-retrieve',
    schema: McpAnalyticsIntentClustersRetrieveSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsIntentClustersRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPIntentClusterSnapshot[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/`,
        })
        return result
    },
})

const McpAnalyticsSessionsGenerateIntentSchema = McpAnalyticsSessionsGenerateIntentParams.omit({
    project_id: true,
}).extend(McpAnalyticsSessionsGenerateIntentQueryParams.shape)

const mcpAnalyticsSessionsGenerateIntent = (): ToolBase<
    typeof McpAnalyticsSessionsGenerateIntentSchema,
    Schemas.MCPSessionIntent
> => ({
    name: 'mcp-analytics-sessions-generate-intent',
    schema: McpAnalyticsSessionsGenerateIntentSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsGenerateIntentSchema>) => {
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

const McpAnalyticsSessionsListSchema = McpAnalyticsSessionsListQueryParams

const mcpAnalyticsSessionsList = (): ToolBase<
    typeof McpAnalyticsSessionsListSchema,
    WithPostHogUrl<Schemas.PaginatedMCPSessionList>
> => ({
    name: 'mcp-analytics-sessions-list',
    schema: McpAnalyticsSessionsListSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPSessionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/mcp-analytics')
    },
})

const McpAnalyticsSessionsToolCallsSchema = McpAnalyticsSessionsToolCallsParams.omit({ project_id: true }).extend(
    McpAnalyticsSessionsToolCallsQueryParams.shape
)

const mcpAnalyticsSessionsToolCalls = (): ToolBase<
    typeof McpAnalyticsSessionsToolCallsSchema,
    WithPostHogUrl<Schemas.PaginatedMCPToolCallList>
> => ({
    name: 'mcp-analytics-sessions-tool-calls',
    schema: McpAnalyticsSessionsToolCallsSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsToolCallsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPToolCallList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/tool_calls/`,
            query: {
                date_from: params.date_from,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/mcp-analytics')
    },
})

const McpFeedbackSubmitSchema = McpAnalyticsFeedbackCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpFeedbackSubmit = (): ToolBase<typeof McpFeedbackSubmitSchema, Schemas.MCPAnalyticsSubmission> => ({
    name: 'mcp-feedback-submit',
    schema: McpFeedbackSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof McpFeedbackSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.feedback !== undefined) {
            body['feedback'] = params.feedback
        }
        if (params.category !== undefined) {
            body['category'] = params.category
        }
        const result = await context.api.request<Schemas.MCPAnalyticsSubmission>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/feedback/`,
            body,
        })
        return result
    },
})

const McpMissingCapabilityReportSchema = McpAnalyticsMissingCapabilitiesCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpMissingCapabilityReport = (): ToolBase<
    typeof McpMissingCapabilityReportSchema,
    Schemas.MCPAnalyticsSubmission
> => ({
    name: 'mcp-missing-capability-report',
    schema: McpMissingCapabilityReportSchema,
    handler: async (context: Context, params: z.infer<typeof McpMissingCapabilityReportSchema>) => {
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

const integer = z.coerce.number().int()

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
        .describe('End of the date range. Same format as date_from. Omit or null for "now".')
        .optional(),
    daysOfWeek: z
        .union([z.array(integer), z.null()])
        .describe(
            'Restrict the query to events occurring on these ISO days of week (1=Monday … 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries.'
        )
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

const PropertyFilterBaseValue = z.union([z.string(), z.coerce.number(), z.coerce.boolean()])

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

const PersonMetadataPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z
        .literal('person_metadata')
        .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON')
        .default('person_metadata'),
    value: PropertyFilterValue.optional(),
})

const ElementPropertyFilter = z.object({
    key: z.enum(['tag_name', 'text', 'href', 'selector']),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('element').default('element'),
    value: PropertyFilterValue.optional(),
})

const EventMetadataPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('event_metadata').default('event_metadata'),
    value: PropertyFilterValue.optional(),
})

const SessionPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('session').default('session'),
    value: PropertyFilterValue.optional(),
})

const CohortPropertyFilter = z.object({
    cohort_name: z.string().optional(),
    key: z.literal('id').default('id'),
    label: z.string().optional(),
    operator: PropertyOperator.default('in'),
    type: z.literal('cohort').default('cohort'),
    value: z.coerce.number().int(),
})

const DurationType = z.enum(['duration', 'active_seconds', 'inactive_seconds'])

const RecordingPropertyFilter = z.object({
    key: z.union([
        DurationType,
        z.literal('snapshot_source'),
        z.literal('visited_page'),
        z.literal('comment_text'),
        z.literal('click_count'),
        z.literal('keypress_count'),
        z.literal('mouse_activity_count'),
    ]),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('recording').default('recording'),
    value: PropertyFilterValue.optional(),
})

const LogEntryPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('log_entry').default('log_entry'),
    value: PropertyFilterValue.optional(),
})

const GroupPropertyFilter = z.object({
    group_key_names: z.record(z.string(), z.string()).optional(),
    group_type_index: z.union([z.coerce.number().int(), z.null()]).optional(),
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('group').default('group'),
    value: PropertyFilterValue.optional(),
})

const FeaturePropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('feature').describe('Event property with "$feature/" prepended').default('feature'),
    value: PropertyFilterValue.optional(),
})

const FlagPropertyFilter = z.object({
    key: z.string().describe('The key should be the flag ID'),
    label: z.string().optional(),
    operator: z
        .literal('flag_evaluates_to')
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies')
        .default('flag_evaluates_to'),
    type: z.literal('flag').describe('Feature flag dependency').default('flag'),
    value: z.union([z.coerce.boolean(), z.string()]).describe('The value can be true, false, or a variant name'),
})

const HogQLPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    type: z.literal('hogql').default('hogql'),
    value: PropertyFilterValue.optional(),
})

const EmptyPropertyFilter = z.object({
    type: z.literal('empty').default('empty').optional(),
})

const DataWarehousePropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('data_warehouse').default('data_warehouse'),
    value: PropertyFilterValue.optional(),
})

const DataWarehousePersonPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('data_warehouse_person_property').default('data_warehouse_person_property'),
    value: PropertyFilterValue.optional(),
})

const ErrorTrackingIssueFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('error_tracking_issue').default('error_tracking_issue'),
    value: PropertyFilterValue.optional(),
})

const LogPropertyFilterType = z.enum(['log', 'log_attribute', 'log_resource_attribute'])

const LogPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: LogPropertyFilterType,
    value: PropertyFilterValue.optional(),
})

const MetricPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('metric_attribute').default('metric_attribute'),
    value: PropertyFilterValue.optional(),
})

const SpanPropertyFilterType = z.enum(['span', 'span_attribute', 'span_resource_attribute'])

const SpanPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: SpanPropertyFilterType,
    value: PropertyFilterValue.optional(),
})

const RevenueAnalyticsPropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('revenue_analytics').default('revenue_analytics'),
    value: PropertyFilterValue.optional(),
})

const WorkflowVariablePropertyFilter = z.object({
    key: z.string(),
    label: z.string().optional(),
    operator: PropertyOperator,
    type: z.literal('workflow_variable').default('workflow_variable'),
    value: PropertyFilterValue.optional(),
})

const AnyPropertyFilter = z.union([
    EventPropertyFilter,
    PersonPropertyFilter,
    PersonMetadataPropertyFilter,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    SessionPropertyFilter,
    CohortPropertyFilter,
    RecordingPropertyFilter,
    LogEntryPropertyFilter,
    GroupPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
    MetricPropertyFilter,
    SpanPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    WorkflowVariablePropertyFilter,
])

const MCPHarnessBreakdownQuery = z.object({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.coerce.boolean().optional(),
    kind: z.literal('MCPHarnessBreakdownQuery').default('MCPHarnessBreakdownQuery'),
    properties: z.array(AnyPropertyFilter).optional(),
    toolName: z
        .string()
        .describe('When set, scope to a single effective tool\'s new-SDK calls (the per-tool "By harness" table).')
        .optional(),
})

const MCPToolStatsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolStatsQuery').default('MCPToolStatsQuery'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolDailyStatsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolDailyStatsQuery').default('MCPToolDailyStatsQuery'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolFailuresQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolFailuresQuery').default('MCPToolFailuresQuery'),
    toolName: z.string().describe('The raw $mcp_tool_name to scope $exception events to.'),
})

const MCPToolTopUsersQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolTopUsersQuery').default('MCPToolTopUsersQuery'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolNeighborsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolNeighborsQuery').default('MCPToolNeighborsQuery'),
    neighborDirection: z
        .enum(['before', 'after'])
        .describe('Whether to count tools called immediately before or after the target tool.'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolSampleIntentsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolSampleIntentsQuery').default('MCPToolSampleIntentsQuery'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

const MCPToolDescriptionsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MCPToolDescriptionsQuery').default('MCPToolDescriptionsQuery'),
    toolName: z
        .string()
        .describe('The effective tool name to scope to (matched against the single-exec-resolved tool name).'),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-analytics-intent-clusters-recompute': mcpAnalyticsIntentClustersRecompute,
    'mcp-analytics-intent-clusters-retrieve': mcpAnalyticsIntentClustersRetrieve,
    'mcp-analytics-sessions-generate-intent': mcpAnalyticsSessionsGenerateIntent,
    'mcp-analytics-sessions-list': mcpAnalyticsSessionsList,
    'mcp-analytics-sessions-tool-calls': mcpAnalyticsSessionsToolCalls,
    'mcp-feedback-submit': mcpFeedbackSubmit,
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
}
