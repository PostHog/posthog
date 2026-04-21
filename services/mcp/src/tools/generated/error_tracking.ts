// AUTO-GENERATED from products/error_tracking/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ErrorTrackingAssignmentRulesCreateBody,
    ErrorTrackingAssignmentRulesListQueryParams,
    ErrorTrackingGroupingRulesCreateBody,
    ErrorTrackingIssuesListQueryParams,
    ErrorTrackingIssuesMergeCreateBody,
    ErrorTrackingIssuesMergeCreateParams,
    ErrorTrackingIssuesPartialUpdateBody,
    ErrorTrackingIssuesPartialUpdateParams,
    ErrorTrackingIssuesRetrieveParams,
    ErrorTrackingIssuesSplitCreateBody,
    ErrorTrackingIssuesSplitCreateParams,
    ErrorTrackingSuppressionRulesListQueryParams,
} from '@/generated/error_tracking/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ErrorTrackingAssignmentRulesListSchema = ErrorTrackingAssignmentRulesListQueryParams

const errorTrackingAssignmentRulesList = (): ToolBase<
    typeof ErrorTrackingAssignmentRulesListSchema,
    Schemas.PaginatedErrorTrackingAssignmentRuleList
> => ({
    name: 'error-tracking-assignment-rules-list',
    schema: ErrorTrackingAssignmentRulesListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAssignmentRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedErrorTrackingAssignmentRuleList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/assignment_rules/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ErrorTrackingAssignmentRulesCreateSchema = ErrorTrackingAssignmentRulesCreateBody

const errorTrackingAssignmentRulesCreate = (): ToolBase<
    typeof ErrorTrackingAssignmentRulesCreateSchema,
    Schemas.ErrorTrackingAssignmentRule
> => ({
    name: 'error-tracking-assignment-rules-create',
    schema: ErrorTrackingAssignmentRulesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAssignmentRulesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        const result = await context.api.request<Schemas.ErrorTrackingAssignmentRule>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/assignment_rules/`,
            body,
        })
        return result
    },
})

const ErrorTrackingGroupingRulesListSchema = z.object({})

const errorTrackingGroupingRulesList = (): ToolBase<
    typeof ErrorTrackingGroupingRulesListSchema,
    Schemas.ErrorTrackingGroupingRuleListResponse
> => ({
    name: 'error-tracking-grouping-rules-list',
    schema: ErrorTrackingGroupingRulesListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingGroupingRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ErrorTrackingGroupingRuleListResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/grouping_rules/`,
        })
        return result
    },
})

const ErrorTrackingGroupingRulesCreateSchema = ErrorTrackingGroupingRulesCreateBody

const errorTrackingGroupingRulesCreate = (): ToolBase<
    typeof ErrorTrackingGroupingRulesCreateSchema,
    Schemas.ErrorTrackingGroupingRule
> => ({
    name: 'error-tracking-grouping-rules-create',
    schema: ErrorTrackingGroupingRulesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingGroupingRulesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.ErrorTrackingGroupingRule>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/grouping_rules/`,
            body,
        })
        return result
    },
})

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
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            const filtered = {
                ...result,
                results: (result.results ?? []).map((item: any) =>
                    pickResponseFields(item, ['id', 'status', 'name', 'first_seen', 'assignee'])
                ),
            } as typeof result
            return await withPostHogUrl(
                context,
                {
                    ...filtered,
                    results: await Promise.all(
                        (filtered.results ?? []).map((item) =>
                            withPostHogUrl(context, item, `/error_tracking/${item.id}`)
                        )
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
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/`,
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
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${result.id}`)
        },
    })

const ErrorTrackingIssuesMergeCreateSchema = ErrorTrackingIssuesMergeCreateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesMergeCreateBody.shape
)

const errorTrackingIssuesMergeCreate = (): ToolBase<
    typeof ErrorTrackingIssuesMergeCreateSchema,
    Schemas.ErrorTrackingIssueMergeResponse
> => ({
    name: 'error-tracking-issues-merge-create',
    schema: ErrorTrackingIssuesMergeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesMergeCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.ErrorTrackingIssueMergeResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/merge/`,
            body,
        })
        return result
    },
})

const ErrorTrackingIssuesSplitCreateSchema = ErrorTrackingIssuesSplitCreateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesSplitCreateBody.shape
)

const errorTrackingIssuesSplitCreate = (): ToolBase<
    typeof ErrorTrackingIssuesSplitCreateSchema,
    Schemas.ErrorTrackingIssueSplitResponse
> => ({
    name: 'error-tracking-issues-split-create',
    schema: ErrorTrackingIssuesSplitCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesSplitCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.fingerprints !== undefined) {
            body['fingerprints'] = params.fingerprints
        }
        const result = await context.api.request<Schemas.ErrorTrackingIssueSplitResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/split/`,
            body,
        })
        return result
    },
})

const ErrorTrackingSuppressionRulesListSchema = ErrorTrackingSuppressionRulesListQueryParams

const errorTrackingSuppressionRulesList = (): ToolBase<
    typeof ErrorTrackingSuppressionRulesListSchema,
    Schemas.PaginatedErrorTrackingSuppressionRuleList
> => ({
    name: 'error-tracking-suppression-rules-list',
    schema: ErrorTrackingSuppressionRulesListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSuppressionRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedErrorTrackingSuppressionRuleList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/suppression_rules/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-assignment-rules-list': errorTrackingAssignmentRulesList,
    'error-tracking-assignment-rules-create': errorTrackingAssignmentRulesCreate,
    'error-tracking-grouping-rules-list': errorTrackingGroupingRulesList,
    'error-tracking-grouping-rules-create': errorTrackingGroupingRulesCreate,
    'error-tracking-issues-list': errorTrackingIssuesList,
    'error-tracking-issues-retrieve': errorTrackingIssuesRetrieve,
    'error-tracking-issues-partial-update': errorTrackingIssuesPartialUpdate,
    'error-tracking-issues-merge-create': errorTrackingIssuesMergeCreate,
    'error-tracking-issues-split-create': errorTrackingIssuesSplitCreate,
    'error-tracking-suppression-rules-list': errorTrackingSuppressionRulesList,
}
