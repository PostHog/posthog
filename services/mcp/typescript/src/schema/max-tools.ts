import { z } from 'zod'

// ExecuteSQLTool schemas
export const MaxExecuteSQLToolArgsSchema = z.object({
    query: z.string().describe('The final SQL query to be executed.'),
    viz_title: z
        .string()
        .describe(
            'Short, concise name of the SQL query (2-5 words) that will be displayed as a header in the visualization.'
        ),
    viz_description: z
        .string()
        .describe(
            'Short, concise summary of the SQL query (1 sentence) that will be displayed as a description in the visualization.'
        ),
})

export type MaxExecuteSQLToolArgs = z.infer<typeof MaxExecuteSQLToolArgsSchema>

// CreateInsightTool schemas
export const InsightTypeSchema = z.enum(['trends', 'funnel', 'retention'])

export const MaxCreateInsightToolArgsSchema = z.object({
    query_description: z.string().describe('A plan of the query to generate based on the template.'),
    insight_type: InsightTypeSchema.describe('The type of insight to generate.'),
    viz_title: z
        .string()
        .describe(
            'Short, concise name of the insight (2-7 words) that will be displayed as a header in the insight visualization.'
        ),
    viz_description: z
        .string()
        .describe(
            'Short, concise summary of the insight (1 sentence) that will be displayed as a description in the insight visualization.'
        ),
})

export type MaxCreateInsightToolArgs = z.infer<typeof MaxCreateInsightToolArgsSchema>

// UpsertDashboardTool schemas - discriminated union with action field
export const CreateDashboardActionSchema = z.object({
    action: z.literal('create'),
    insight_ids: z
        .array(z.string())
        .describe(
            'The IDs of the insights to be included in the dashboard. It might be a mix of existing and new insights.'
        ),
    name: z
        .string()
        .describe(
            'A short and concise (3-7 words) name of the dashboard. It will be displayed as a header in the dashboard tile.'
        ),
    description: z.string().describe('A short and concise description of the dashboard.'),
})

export const UpdateDashboardActionSchema = z.object({
    action: z.literal('update'),
    dashboard_id: z.string().describe('Provide the ID of the dashboard to be update it.'),
    insight_ids: z
        .array(z.string())
        .nullable()
        .optional()
        .describe(
            'The IDs of the insights for the dashboard. Replaces all existing insights. Order determines positional mapping for layout preservation.'
        ),
    name: z
        .string()
        .nullable()
        .optional()
        .describe(
            'A short and concise (3-7 words) name of the dashboard. If not provided, the dashboard name will not be updated.'
        ),
    description: z
        .string()
        .nullable()
        .optional()
        .describe(
            'A short and concise description of the dashboard. If not provided, the dashboard description will not be updated.'
        ),
})

export const UpsertDashboardActionSchema = z.discriminatedUnion('action', [
    CreateDashboardActionSchema,
    UpdateDashboardActionSchema,
])

export const MaxUpsertDashboardToolArgsSchema = z.object({
    action: UpsertDashboardActionSchema.describe(
        'The action to perform. Either create a new dashboard or update an existing one.'
    ),
})

export type MaxUpsertDashboardToolArgs = z.infer<typeof MaxUpsertDashboardToolArgsSchema>

// Recording filter schemas (shared between filter and summarize tools)
export const RecordingFilterGroupSchema = z.object({
    type: z.enum(['AND', 'OR']).describe('Logical operator for combining filters'),
    values: z.array(z.record(z.unknown())).describe('Array of property filters or nested filter groups'),
})

export const RecordingUniversalFiltersSchema = z.object({
    duration: z
        .array(z.record(z.unknown()))
        .describe('Duration filters array. Each filter has key, value, operator, and type fields.'),
    filter_group: RecordingFilterGroupSchema.describe('Property filter group with nested AND/OR logic'),
    date_from: z.string().nullable().optional().describe('Start date (relative like "-7d" or absolute)'),
    date_to: z.string().nullable().optional().describe('End date'),
    filter_test_accounts: z.boolean().nullable().optional().describe('Exclude internal/test accounts'),
    limit: z.number().nullable().optional().describe('Maximum number of recordings to return'),
    order: z.enum(['start_time', 'console_error_count', 'active_seconds']).optional().describe('Sort order field'),
    order_direction: z.enum(['ASC', 'DESC']).optional().describe('Sort direction'),
})

// FilterSessionRecordingsTool schemas
export const MaxFilterSessionRecordingsToolArgsSchema = z.object({
    recordings_filters: RecordingUniversalFiltersSchema.describe(
        "User's question converted into a recordings query filter object with required duration and filter_group fields."
    ),
})

export type MaxFilterSessionRecordingsToolArgs = z.infer<typeof MaxFilterSessionRecordingsToolArgsSchema>

// SummarizeSessionsTool schemas
export const MaxSummarizeSessionsToolArgsSchema = z.object({
    recordings_filters_or_explicit_session_ids: z
        .union([RecordingUniversalFiltersSchema, z.array(z.string())])
        .describe(
            'Either a recordings filter object (with required duration and filter_group fields) or a list of explicit session UUIDs to summarize.'
        ),
    summary_title: z
        .string()
        .describe(
            'The name of the summary that is expected to be generated. Should cover in 3-7 words what sessions would be summarized.'
        ),
})

export type MaxSummarizeSessionsToolArgs = z.infer<typeof MaxSummarizeSessionsToolArgsSchema>

// SearchErrorTrackingIssuesTool schemas
export const ErrorTrackingDateRangeSchema = z.object({
    date_from: z.string().describe('Start date (relative like "-7d" or absolute "2024-12-01")'),
    date_to: z.string().nullable().optional().describe('End date (null for "until now", or absolute date)'),
})

export const ErrorTrackingQuerySchema = z.object({
    status: z
        .enum(['active', 'resolved', 'pending_release', 'suppressed', 'archived', 'all'])
        .nullable()
        .optional()
        .describe('Filter by issue status. Default: "active"'),
    searchQuery: z.string().nullable().optional().describe('Free text search across exception type, message, and stack traces'),
    dateRange: ErrorTrackingDateRangeSchema.describe('Time range for the query (REQUIRED)'),
    orderBy: z
        .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions', 'revenue'])
        .describe('Sort results by this field (REQUIRED)'),
    orderDirection: z.enum(['DESC', 'ASC']).nullable().optional().describe('Sort direction. Default: "DESC"'),
    limit: z.number().nullable().optional().describe('Number of results to return (1-100, default 50)'),
    filterGroup: z.record(z.unknown()).nullable().optional().describe('Property filters for advanced filtering'),
    filterTestAccounts: z.boolean().nullable().optional().describe('Exclude internal/test accounts'),
    volumeResolution: z.number().default(1).describe('Resolution for volume chart data. Use 1 for daily buckets.'),
})

export const MaxSearchErrorTrackingIssuesToolArgsSchema = z.object({
    query: ErrorTrackingQuerySchema.describe("User's question converted into an error tracking query."),
    cursor: z
        .string()
        .nullable()
        .optional()
        .describe('Pagination cursor from previous search results. Pass this to get the next page of results.'),
})

export type MaxSearchErrorTrackingIssuesToolArgs = z.infer<typeof MaxSearchErrorTrackingIssuesToolArgsSchema>
