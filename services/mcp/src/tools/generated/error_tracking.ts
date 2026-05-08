// AUTO-GENERATED from products/error_tracking/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ErrorTrackingAssignmentRulesCreateBody,
    ErrorTrackingAssignmentRulesListQueryParams,
    ErrorTrackingGroupingRulesCreateBody,
    ErrorTrackingGroupingRulesUpdateBody,
    ErrorTrackingGroupingRulesUpdateParams,
    ErrorTrackingIssuesMergeCreateBody,
    ErrorTrackingIssuesMergeCreateParams,
    ErrorTrackingIssuesPartialUpdateBody,
    ErrorTrackingIssuesPartialUpdateParams,
    ErrorTrackingIssuesSplitCreateBody,
    ErrorTrackingIssuesSplitCreateParams,
    ErrorTrackingQueryIssueCreateBody,
    ErrorTrackingQueryIssueEventsCreateBody,
    ErrorTrackingQueryIssuesListCreateBody,
    ErrorTrackingSuppressionRulesCreateBody,
    ErrorTrackingSuppressionRulesListQueryParams,
    ErrorTrackingSymbolSetsDownloadRetrieveParams,
    ErrorTrackingSymbolSetsListQueryParams,
    ErrorTrackingSymbolSetsRetrieveParams,
} from '@/generated/error_tracking/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

const ErrorTrackingGroupingRulesUpdateSchema = ErrorTrackingGroupingRulesUpdateParams.omit({ project_id: true }).extend(
    ErrorTrackingGroupingRulesUpdateBody.shape
)

const errorTrackingGroupingRulesUpdate = (): ToolBase<
    typeof ErrorTrackingGroupingRulesUpdateSchema,
    Schemas.ErrorTrackingGroupingRule
> => ({
    name: 'error-tracking-grouping-rules-update',
    schema: ErrorTrackingGroupingRulesUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingGroupingRulesUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.order_key !== undefined) {
            body['order_key'] = params.order_key
        }
        if (params.disabled_data !== undefined) {
            body['disabled_data'] = params.disabled_data
        }
        const result = await context.api.request<Schemas.ErrorTrackingGroupingRule>({
            method: 'PUT',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/grouping_rules/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
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

const ErrorTrackingSuppressionRulesCreateSchema = ErrorTrackingSuppressionRulesCreateBody

const errorTrackingSuppressionRulesCreate = (): ToolBase<
    typeof ErrorTrackingSuppressionRulesCreateSchema,
    Schemas.ErrorTrackingSuppressionRule
> => ({
    name: 'error-tracking-suppression-rules-create',
    schema: ErrorTrackingSuppressionRulesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSuppressionRulesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.sampling_rate !== undefined) {
            body['sampling_rate'] = params.sampling_rate
        }
        const result = await context.api.request<Schemas.ErrorTrackingSuppressionRule>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/suppression_rules/`,
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

const ErrorTrackingSymbolSetsDownloadRetrieveSchema = ErrorTrackingSymbolSetsDownloadRetrieveParams.omit({
    project_id: true,
})

const errorTrackingSymbolSetsDownloadRetrieve = (): ToolBase<
    typeof ErrorTrackingSymbolSetsDownloadRetrieveSchema,
    Schemas._SymbolSetDownloadResponse
> => ({
    name: 'error-tracking-symbol-sets-download-retrieve',
    schema: ErrorTrackingSymbolSetsDownloadRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSymbolSetsDownloadRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._SymbolSetDownloadResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/error_tracking/symbol_sets/${encodeURIComponent(String(params.id))}/download/`,
        })
        return result
    },
})

const ErrorTrackingSymbolSetsListSchema = ErrorTrackingSymbolSetsListQueryParams

const errorTrackingSymbolSetsList = (): ToolBase<
    typeof ErrorTrackingSymbolSetsListSchema,
    WithPostHogUrl<Schemas.PaginatedErrorTrackingSymbolSetList>
> => ({
    name: 'error-tracking-symbol-sets-list',
    schema: ErrorTrackingSymbolSetsListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSymbolSetsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedErrorTrackingSymbolSetList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/error_tracking/symbol_sets/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                ref: params.ref,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'ref',
                    'created_at',
                    'last_used',
                    'failure_reason',
                    'has_uploaded_file',
                    'release',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/error_tracking')
    },
})

const ErrorTrackingSymbolSetsRetrieveSchema = ErrorTrackingSymbolSetsRetrieveParams.omit({ project_id: true })

const errorTrackingSymbolSetsRetrieve = (): ToolBase<
    typeof ErrorTrackingSymbolSetsRetrieveSchema,
    Schemas.ErrorTrackingSymbolSet
> => ({
    name: 'error-tracking-symbol-sets-retrieve',
    schema: ErrorTrackingSymbolSetsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSymbolSetsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ErrorTrackingSymbolSet>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/error_tracking/symbol_sets/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'ref',
            'created_at',
            'last_used',
            'failure_reason',
            'has_uploaded_file',
            'release',
        ]) as typeof result
        return filtered
    },
})

const QueryErrorTrackingIssueSchema = ErrorTrackingQueryIssueCreateBody

const queryErrorTrackingIssue = (): ToolBase<
    typeof QueryErrorTrackingIssueSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueDetail>
> =>
    withUiApp('error-issue', {
        name: 'query-error-tracking-issue',
        schema: QueryErrorTrackingIssueSchema,
        handler: async (context: Context, params: z.infer<typeof QueryErrorTrackingIssueSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.issueId !== undefined) {
                body['issueId'] = params.issueId
            }
            if (params.dateRange !== undefined) {
                body['dateRange'] = params.dateRange
            }
            if (params.filterTestAccounts !== undefined) {
                body['filterTestAccounts'] = params.filterTestAccounts
            }
            if (params.volumeResolution !== undefined) {
                body['volumeResolution'] = params.volumeResolution
            }
            if (params.includeSparkline !== undefined) {
                body['includeSparkline'] = params.includeSparkline
            }
            const result = await context.api.request<Schemas.ErrorTrackingIssueDetail>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/query/issue/`,
                body,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${params.issueId}`)
        },
    })

const QueryErrorTrackingIssueEventsSchema = ErrorTrackingQueryIssueEventsCreateBody

const queryErrorTrackingIssueEvents = (): ToolBase<
    typeof QueryErrorTrackingIssueEventsSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueEventsResponse>
> =>
    withUiApp('error-details', {
        name: 'query-error-tracking-issue-events',
        schema: QueryErrorTrackingIssueEventsSchema,
        handler: async (context: Context, params: z.infer<typeof QueryErrorTrackingIssueEventsSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.issueId !== undefined) {
                body['issueId'] = params.issueId
            }
            if (params.dateRange !== undefined) {
                body['dateRange'] = params.dateRange
            }
            if (params.filterTestAccounts !== undefined) {
                body['filterTestAccounts'] = params.filterTestAccounts
            }
            if (params.filterGroup !== undefined) {
                body['filterGroup'] = params.filterGroup
            }
            if (params.searchQuery !== undefined) {
                body['searchQuery'] = params.searchQuery
            }
            if (params.orderDirection !== undefined) {
                body['orderDirection'] = params.orderDirection
            }
            if (params.limit !== undefined) {
                body['limit'] = params.limit
            }
            if (params.offset !== undefined) {
                body['offset'] = params.offset
            }
            if (params.verbosity !== undefined) {
                body['verbosity'] = params.verbosity
            }
            if (params.onlyAppFrames !== undefined) {
                body['onlyAppFrames'] = params.onlyAppFrames
            }
            const result = await context.api.request<Schemas.ErrorTrackingIssueEventsResponse>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/query/issue_events/`,
                body,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${params.issueId}`)
        },
    })

const QueryErrorTrackingIssuesListSchema = ErrorTrackingQueryIssuesListCreateBody

const queryErrorTrackingIssuesList = (): ToolBase<
    typeof QueryErrorTrackingIssuesListSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssuesListResponse>
> =>
    withUiApp('error-issue-list', {
        name: 'query-error-tracking-issues-list',
        schema: QueryErrorTrackingIssuesListSchema,
        handler: async (context: Context, params: z.infer<typeof QueryErrorTrackingIssuesListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.dateRange !== undefined) {
                body['dateRange'] = params.dateRange
            }
            if (params.status !== undefined) {
                body['status'] = params.status
            }
            if (params.assignee !== undefined) {
                body['assignee'] = params.assignee
            }
            if (params.filterTestAccounts !== undefined) {
                body['filterTestAccounts'] = params.filterTestAccounts
            }
            if (params.searchQuery !== undefined) {
                body['searchQuery'] = params.searchQuery
            }
            if (params.filterGroup !== undefined) {
                body['filterGroup'] = params.filterGroup
            }
            if (params.orderBy !== undefined) {
                body['orderBy'] = params.orderBy
            }
            if (params.orderDirection !== undefined) {
                body['orderDirection'] = params.orderDirection
            }
            if (params.limit !== undefined) {
                body['limit'] = params.limit
            }
            if (params.offset !== undefined) {
                body['offset'] = params.offset
            }
            if (params.volumeResolution !== undefined) {
                body['volumeResolution'] = params.volumeResolution
            }
            if (params.library !== undefined) {
                body['library'] = params.library
            }
            if (params.release !== undefined) {
                body['release'] = params.release
            }
            if (params.fingerprint !== undefined) {
                body['fingerprint'] = params.fingerprint
            }
            if (params.user !== undefined) {
                body['user'] = params.user
            }
            if (params.personId !== undefined) {
                body['personId'] = params.personId
            }
            if (params.url !== undefined) {
                body['url'] = params.url
            }
            if (params.filePath !== undefined) {
                body['filePath'] = params.filePath
            }
            const result = await context.api.request<Schemas.ErrorTrackingIssuesListResponse>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/query/issues/`,
                body,
            })
            const filtered = {
                ...result,
                results: (result.results ?? []).map((item: any) =>
                    pickResponseFields(item, [
                        'id',
                        'name',
                        'description',
                        'status',
                        'first_seen',
                        'last_seen',
                        'library',
                        'source',
                        'assignee',
                        'aggregations',
                    ])
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-assignment-rules-create': errorTrackingAssignmentRulesCreate,
    'error-tracking-assignment-rules-list': errorTrackingAssignmentRulesList,
    'error-tracking-grouping-rules-create': errorTrackingGroupingRulesCreate,
    'error-tracking-grouping-rules-list': errorTrackingGroupingRulesList,
    'error-tracking-grouping-rules-update': errorTrackingGroupingRulesUpdate,
    'error-tracking-issues-merge-create': errorTrackingIssuesMergeCreate,
    'error-tracking-issues-partial-update': errorTrackingIssuesPartialUpdate,
    'error-tracking-issues-split-create': errorTrackingIssuesSplitCreate,
    'error-tracking-suppression-rules-create': errorTrackingSuppressionRulesCreate,
    'error-tracking-suppression-rules-list': errorTrackingSuppressionRulesList,
    'error-tracking-symbol-sets-download-retrieve': errorTrackingSymbolSetsDownloadRetrieve,
    'error-tracking-symbol-sets-list': errorTrackingSymbolSetsList,
    'error-tracking-symbol-sets-retrieve': errorTrackingSymbolSetsRetrieve,
    'query-error-tracking-issue': queryErrorTrackingIssue,
    'query-error-tracking-issue-events': queryErrorTrackingIssueEvents,
    'query-error-tracking-issues-list': queryErrorTrackingIssuesList,
}
