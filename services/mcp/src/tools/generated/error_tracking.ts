// AUTO-GENERATED from products/error_tracking/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ErrorTrackingIssuesListQueryParams,
    ErrorTrackingIssuesPartialUpdateBody,
    ErrorTrackingIssuesPartialUpdateParams,
    ErrorTrackingIssuesRetrieveParams,
} from '@/generated/error_tracking/api'
import { withUiApp } from '@/resources/ui-apps'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ErrorTrackingIssuesListSchema = ErrorTrackingIssuesListQueryParams

const errorTrackingIssuesList = (): ToolBase<
    typeof ErrorTrackingIssuesListSchema,
    WithPostHogUrl<Schemas.PaginatedErrorTrackingIssueFullList>
> =>
    withUiApp('error-issue-list', {
        name: 'error-tracking-issues-list',
        schema: ErrorTrackingIssuesListSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedErrorTrackingIssueFullList>({
                method: 'GET',
                path: `/api/environments/${projectId}/error_tracking/issues/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            return await withPostHogUrl(
                context,
                {
                    ...result,
                    results: await Promise.all(
                        result.results.map((item) => withPostHogUrl(context, item, `/error_tracking/${item.id}`))
                    ),
                },
                '/error_tracking'
            )
        },
    })

const ErrorTrackingIssuesRetrieveSchema = ErrorTrackingIssuesRetrieveParams.omit({ project_id: true })

const errorTrackingIssuesRetrieve = (): ToolBase<
    typeof ErrorTrackingIssuesRetrieveSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueFull>
> =>
    withUiApp('error-issue', {
        name: 'error-tracking-issues-retrieve',
        schema: ErrorTrackingIssuesRetrieveSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesRetrieveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.ErrorTrackingIssueFull>({
                method: 'GET',
                path: `/api/environments/${projectId}/error_tracking/issues/${params.id}/`,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${result.id}`)
        },
    })

const ErrorTrackingIssuesPartialUpdateSchema = ErrorTrackingIssuesPartialUpdateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesPartialUpdateBody.shape
)

const errorTrackingIssuesPartialUpdate = (): ToolBase<
    typeof ErrorTrackingIssuesPartialUpdateSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueFull>
> =>
    withUiApp('error-issue', {
        name: 'error-tracking-issues-partial-update',
        schema: ErrorTrackingIssuesPartialUpdateSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesPartialUpdateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.status !== undefined) {
                body['status'] = params.status
            }
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.first_seen !== undefined) {
                body['first_seen'] = params.first_seen
            }
            if (params.assignee !== undefined) {
                body['assignee'] = params.assignee
            }
            if (params.external_issues !== undefined) {
                body['external_issues'] = params.external_issues
            }
            const result = await context.api.request<Schemas.ErrorTrackingIssueFull>({
                method: 'PATCH',
                path: `/api/environments/${projectId}/error_tracking/issues/${params.id}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${result.id}`)
        },
    })

// --- Query wrapper schemas from schema.json ---

const integer = z.coerce.number().int()

const ErrorTrackingIssueAssigneeType = z.enum(['user', 'role'])

const ErrorTrackingIssueAssignee = z.object({
    id: z.union([integer, z.string()]),
    type: ErrorTrackingIssueAssigneeType,
})

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
    explicitDate: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        )
        .default(false)
        .optional(),
})

const ErrorTrackingOrderBy = z.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])

const ErrorTrackingIssueStatus = z.enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])

const ErrorTrackingQueryStatus = z.union([ErrorTrackingIssueStatus, z.literal('all')])

const AssistantErrorTrackingQuery = z.object({
    assignee: z.union([ErrorTrackingIssueAssignee, z.null()]).describe('Filter by assignee.').optional(),
    dateRange: DateRange.describe('Date range to filter results.').optional(),
    filterTestAccounts: z.coerce.boolean().describe('Whether to filter out test accounts.').optional(),
    issueId: z.string().describe('Filter to a specific error tracking issue by ID.').optional(),
    kind: z.literal('ErrorTrackingQuery').default('ErrorTrackingQuery'),
    limit: integer.optional(),
    offset: integer.optional(),
    orderBy: ErrorTrackingOrderBy.describe('Field to sort results by.').optional(),
    orderDirection: z.enum(['ASC', 'DESC']).describe('Sort direction.').optional(),
    searchQuery: z.string().describe('Free-text search across exception type, message, and stack frames.').optional(),
    status: ErrorTrackingQueryStatus.describe('Filter by issue status.').optional(),
    volumeResolution: integer
        .describe('Controls volume chart granularity. Use 1 for sparklines, 0 for counts only.')
        .optional(),
})

const QueryErrorTrackingIssuesSchema = AssistantErrorTrackingQuery.extend({
    limit: AssistantErrorTrackingQuery.shape.limit.default(50).optional(),
    orderBy: AssistantErrorTrackingQuery.shape.orderBy.default('occurrences').optional(),
    volumeResolution: AssistantErrorTrackingQuery.shape.volumeResolution.default(1).optional(),
    dateRange: AssistantErrorTrackingQuery.shape.dateRange.default({ date_from: '-7d' }).optional(),
    filterTestAccounts: AssistantErrorTrackingQuery.shape.filterTestAccounts.default(true).optional(),
    status: AssistantErrorTrackingQuery.shape.status.default('active').optional(),
    orderDirection: AssistantErrorTrackingQuery.shape.orderDirection.default('DESC').optional(),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-issues-list': errorTrackingIssuesList,
    'error-tracking-issues-retrieve': errorTrackingIssuesRetrieve,
    'error-tracking-issues-partial-update': errorTrackingIssuesPartialUpdate,
    'query-error-tracking-issues': createQueryWrapper({
        name: 'query-error-tracking-issues',
        schema: QueryErrorTrackingIssuesSchema,
        kind: 'ErrorTrackingQuery',
        uiResourceUri: 'ui://posthog/error-issue-list.html',
        urlPrefix: '/error_tracking',
    }),
}
