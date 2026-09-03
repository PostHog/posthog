// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/workflows/api'
import { withUiApp } from '@/resources/ui-apps'
import { WorkflowActionEmailPatchSchema, WorkflowGraphPatchSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsCreateSchema = () => {
    const HogFlowsCreateBody = orvalSchemas.HogFlowsCreateBody()
    return HogFlowsCreateBody
}

const workflowsCreate = (): ToolBase<ReturnType<typeof WorkflowsCreateSchema>, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-create',
        schema: WorkflowsCreateSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsCreateSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.status !== undefined) {
                body['status'] = params.status
            }
            if (params.origin_product !== undefined) {
                body['origin_product'] = params.origin_product
            }
            if (params.trigger_masking !== undefined) {
                body['trigger_masking'] = params.trigger_masking
            }
            if (params.conversion !== undefined) {
                body['conversion'] = params.conversion
            }
            if (params.exit_condition !== undefined) {
                body['exit_condition'] = params.exit_condition
            }
            if (params.email_sending_rate_limit !== undefined) {
                body['email_sending_rate_limit'] = params.email_sending_rate_limit
            }
            if (params.edges !== undefined) {
                body['edges'] = params.edges
            }
            if (params.actions !== undefined) {
                body['actions'] = params.actions
            }
            if (params.variables !== undefined) {
                body['variables'] = params.variables
            }
            const result = await context.api.request<Schemas.HogFlow>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/`,
                body,
            })
            return await withPostHogUrl(context, result, `/workflows/${result.id}/workflow`)
        },
    })

const WorkflowsDiscardDraftSchema = () => {
    const HogFlowsDiscardDraftCreateParams = orvalSchemas.HogFlowsDiscardDraftCreateParams()
    return HogFlowsDiscardDraftCreateParams.omit({ project_id: true })
}

const workflowsDiscardDraft = (): ToolBase<ReturnType<typeof WorkflowsDiscardDraftSchema>, Schemas.HogFlow> =>
    withUiApp('workflow', {
        name: 'workflows-discard-draft',
        schema: WorkflowsDiscardDraftSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsDiscardDraftSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.HogFlow>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/discard_draft/`,
            })
            return result
        },
    })

const WorkflowsGetSchema = () => {
    const HogFlowsRetrieveParams = orvalSchemas.HogFlowsRetrieveParams()
    return HogFlowsRetrieveParams.omit({ project_id: true })
}

const workflowsGet = (): ToolBase<ReturnType<typeof WorkflowsGetSchema>, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-get',
        schema: WorkflowsGetSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsGetSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.HogFlow>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/workflows/${result.id}/workflow`)
        },
    })

const WorkflowsGetInvocationSchema = () => {
    const HogFlowsInvocationResultRetrieveParams = orvalSchemas.HogFlowsInvocationResultRetrieveParams()
    return HogFlowsInvocationResultRetrieveParams.omit({ project_id: true })
}

const workflowsGetInvocation = (): ToolBase<
    ReturnType<typeof WorkflowsGetInvocationSchema>,
    Schemas.HogInvocationResultDetail
> => ({
    name: 'workflows-get-invocation',
    schema: WorkflowsGetInvocationSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsGetInvocationSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogInvocationResultDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocation_results/${encodeURIComponent(String(params.invocation_id))}/`,
        })
        return result
    },
})

const WorkflowsGetRevisionSchema = () => {
    const HogFlowsRevisionsRetrieveParams = orvalSchemas.HogFlowsRevisionsRetrieveParams()
    return HogFlowsRevisionsRetrieveParams.omit({ project_id: true })
}

const workflowsGetRevision = (): ToolBase<ReturnType<typeof WorkflowsGetRevisionSchema>, Schemas.HogFlowRevision> => ({
    name: 'workflows-get-revision',
    schema: WorkflowsGetRevisionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsGetRevisionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFlowRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/revisions/${encodeURIComponent(String(params.version))}/`,
        })
        return result
    },
})

const WorkflowsGlobalStatsSchema = () => {
    const HogFlowsMetricsGlobalRetrieveQueryParams = orvalSchemas.HogFlowsMetricsGlobalRetrieveQueryParams()
    return HogFlowsMetricsGlobalRetrieveQueryParams
}

const workflowsGlobalStats = (): ToolBase<
    ReturnType<typeof WorkflowsGlobalStatsSchema>,
    WithPostHogUrl<Schemas.WorkflowStatsRow[]>
> => ({
    name: 'workflows-global-stats',
    schema: WorkflowsGlobalStatsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsGlobalStatsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WorkflowStatsRow[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/metrics/global/`,
            query: {
                after: params.after,
                before: params.before,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsListSchema = () => {
    const HogFlowsListQueryParams = orvalSchemas.HogFlowsListQueryParams()
    return HogFlowsListQueryParams
}

const workflowsList = (): ToolBase<
    ReturnType<typeof WorkflowsListSchema>,
    WithPostHogUrl<Schemas.PaginatedHogFlowMinimalList>
> =>
    withUiApp('workflow-list', {
        name: 'workflows-list',
        schema: WorkflowsListSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedHogFlowMinimalList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/`,
                query: {
                    created_at: params.created_at,
                    created_by: params.created_by,
                    id: params.id,
                    limit: params.limit,
                    offset: params.offset,
                    optimisation_enabled: params.optimisation_enabled,
                    origin_product: params.origin_product,
                    search: params.search,
                    status: params.status,
                    trigger: params.trigger,
                    type: params.type,
                    updated_at: params.updated_at,
                },
            })
            return await withPostHogUrl(context, result, '/workflows')
        },
    })

const WorkflowsListBatchJobsSchema = () => {
    const HogFlowsBatchJobsListParams = orvalSchemas.HogFlowsBatchJobsListParams()
    return HogFlowsBatchJobsListParams.omit({ project_id: true })
}

const workflowsListBatchJobs = (): ToolBase<
    ReturnType<typeof WorkflowsListBatchJobsSchema>,
    WithPostHogUrl<Schemas.HogFlowBatchJob[]>
> => ({
    name: 'workflows-list-batch-jobs',
    schema: WorkflowsListBatchJobsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListBatchJobsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFlowBatchJob[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/batch_jobs/`,
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsListInvocationsSchema = () => {
    const HogFlowsInvocationResultsRetrieveParams = orvalSchemas.HogFlowsInvocationResultsRetrieveParams()
    const HogFlowsInvocationResultsRetrieveQueryParams = orvalSchemas.HogFlowsInvocationResultsRetrieveQueryParams()
    return HogFlowsInvocationResultsRetrieveParams.omit({ project_id: true }).extend(
        HogFlowsInvocationResultsRetrieveQueryParams.shape
    )
}

const workflowsListInvocations = (): ToolBase<
    ReturnType<typeof WorkflowsListInvocationsSchema>,
    WithPostHogUrl<Schemas.HogInvocationResult[]>
> => ({
    name: 'workflows-list-invocations',
    schema: WorkflowsListInvocationsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListInvocationsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogInvocationResult[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocation_results/`,
            query: {
                after: params.after,
                before: params.before,
                distinct_id: params.distinct_id,
                error_message_contains: params.error_message_contains,
                limit: params.limit,
                status: params.status,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsListProposalsSchema = () => {
    const HogFlowsProposalsListParams = orvalSchemas.HogFlowsProposalsListParams()
    const HogFlowsProposalsListQueryParams = orvalSchemas.HogFlowsProposalsListQueryParams()
    return HogFlowsProposalsListParams.omit({ project_id: true }).extend(HogFlowsProposalsListQueryParams.shape)
}

const workflowsListProposals = (): ToolBase<
    ReturnType<typeof WorkflowsListProposalsSchema>,
    WithPostHogUrl<Schemas.PaginatedWorkflowProposalList>
> => ({
    name: 'workflows-list-proposals',
    schema: WorkflowsListProposalsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListProposalsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedWorkflowProposalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/proposals/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                status: params.status,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsListRevisionsSchema = () => {
    const HogFlowsRevisionsListParams = orvalSchemas.HogFlowsRevisionsListParams()
    const HogFlowsRevisionsListQueryParams = orvalSchemas.HogFlowsRevisionsListQueryParams()
    return HogFlowsRevisionsListParams.omit({ project_id: true }).extend(HogFlowsRevisionsListQueryParams.shape)
}

const workflowsListRevisions = (): ToolBase<
    ReturnType<typeof WorkflowsListRevisionsSchema>,
    WithPostHogUrl<Schemas.PaginatedHogFlowRevisionBasicList>
> => ({
    name: 'workflows-list-revisions',
    schema: WorkflowsListRevisionsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsListRevisionsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFlowRevisionBasicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/revisions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsLogsSchema = () => {
    const HogFlowsLogsRetrieveParams = orvalSchemas.HogFlowsLogsRetrieveParams()
    const HogFlowsLogsRetrieveQueryParams = orvalSchemas.HogFlowsLogsRetrieveQueryParams()
    return HogFlowsLogsRetrieveParams.omit({ project_id: true }).extend(HogFlowsLogsRetrieveQueryParams.shape)
}

const workflowsLogs = (): ToolBase<ReturnType<typeof WorkflowsLogsSchema>, unknown> => ({
    name: 'workflows-logs',
    schema: WorkflowsLogsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsLogsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/logs/`,
            query: {
                after: params.after,
                before: params.before,
                instance_id: params.instance_id,
                level: params.level,
                limit: params.limit,
                search: params.search,
            },
        })
        return result
    },
})

const WorkflowsPatchActionEmailSchema = () => WorkflowActionEmailPatchSchema

const workflowsPatchActionEmail = (): ToolBase<
    ReturnType<typeof WorkflowsPatchActionEmailSchema>,
    Schemas.HogFlow
> => ({
    name: 'workflows-patch-action-email',
    schema: WorkflowsPatchActionEmailSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsPatchActionEmailSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = WorkflowsPatchActionEmailSchema().parse(params)
        const { id, action_id, ...body } = parsedParams
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(id))}/actions/${encodeURIComponent(String(action_id))}/email/`,
            body,
        })
        return result
    },
})

const WorkflowsPatchGraphSchema = () => WorkflowGraphPatchSchema

const workflowsPatchGraph = (): ToolBase<ReturnType<typeof WorkflowsPatchGraphSchema>, Schemas.HogFlow> => ({
    name: 'workflows-patch-graph',
    schema: WorkflowsPatchGraphSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsPatchGraphSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = WorkflowsPatchGraphSchema().parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(id))}/graph/`,
            body,
        })
        return result
    },
})

const WorkflowsPublishSchema = () => {
    const HogFlowsPublishCreateBody = orvalSchemas.HogFlowsPublishCreateBody()
    const HogFlowsPublishCreateParams = orvalSchemas.HogFlowsPublishCreateParams()
    return HogFlowsPublishCreateParams.omit({ project_id: true }).extend(HogFlowsPublishCreateBody.shape)
}

const workflowsPublish = (): ToolBase<ReturnType<typeof WorkflowsPublishSchema>, Schemas.HogFlowPublishResponse> => ({
    name: 'workflows-publish',
    schema: WorkflowsPublishSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsPublishSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.confirm !== undefined) {
            body['confirm'] = params.confirm
        }
        if (params.confirm_token !== undefined) {
            body['confirm_token'] = params.confirm_token
        }
        const result = await context.api.request<Schemas.HogFlowPublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/publish/`,
            body,
        })
        return result
    },
})

const WorkflowsRestoreRevisionSchema = () => {
    const HogFlowsRevisionsRestoreCreateBody = orvalSchemas.HogFlowsRevisionsRestoreCreateBody()
    const HogFlowsRevisionsRestoreCreateParams = orvalSchemas.HogFlowsRevisionsRestoreCreateParams()
    return HogFlowsRevisionsRestoreCreateParams.omit({ project_id: true }).extend(
        HogFlowsRevisionsRestoreCreateBody.shape
    )
}

const workflowsRestoreRevision = (): ToolBase<ReturnType<typeof WorkflowsRestoreRevisionSchema>, Schemas.HogFlow> => ({
    name: 'workflows-restore-revision',
    schema: WorkflowsRestoreRevisionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsRestoreRevisionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.overwrite !== undefined) {
            body['overwrite'] = params.overwrite
        }
        if (params.expected_draft_updated_at !== undefined) {
            body['expected_draft_updated_at'] = params.expected_draft_updated_at
        }
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/revisions/${encodeURIComponent(String(params.version))}/restore/`,
            body,
        })
        return result
    },
})

const WorkflowsStatsSchema = () => {
    const HogFlowsMetricsRetrieveParams = orvalSchemas.HogFlowsMetricsRetrieveParams()
    const HogFlowsMetricsRetrieveQueryParams = orvalSchemas.HogFlowsMetricsRetrieveQueryParams()
    return HogFlowsMetricsRetrieveParams.omit({ project_id: true }).extend(HogFlowsMetricsRetrieveQueryParams.shape)
}

const workflowsStats = (): ToolBase<ReturnType<typeof WorkflowsStatsSchema>, Schemas.AppMetricsResponse> => ({
    name: 'workflows-stats',
    schema: WorkflowsStatsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsStatsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppMetricsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/metrics/`,
            query: {
                after: params.after,
                before: params.before,
                breakdown_by: params.breakdown_by,
                instance_id: params.instance_id,
                interval: params.interval,
                kind: params.kind,
                name: params.name,
                version: params.version,
            },
        })
        return result
    },
})

const WorkflowsSuggestSchema = () => {
    const HogFlowsProposalsCreateBody = orvalSchemas.HogFlowsProposalsCreateBody()
    const HogFlowsProposalsCreateParams = orvalSchemas.HogFlowsProposalsCreateParams()
    return HogFlowsProposalsCreateParams.omit({ project_id: true }).extend(HogFlowsProposalsCreateBody.shape)
}

const workflowsSuggest = (): ToolBase<ReturnType<typeof WorkflowsSuggestSchema>, Schemas.WorkflowProposal> => ({
    name: 'workflows-suggest',
    schema: WorkflowsSuggestSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsSuggestSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.rationale !== undefined) {
            body['rationale'] = params.rationale
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        if (params.step_id !== undefined) {
            body['step_id'] = params.step_id
        }
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.source_id !== undefined) {
            body['source_id'] = params.source_id
        }
        const result = await context.api.request<Schemas.WorkflowProposal>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/proposals/`,
            body,
        })
        return result
    },
})

const WorkflowsTestRunSchema = () => {
    const HogFlowsInvocationsCreateBody = orvalSchemas.HogFlowsInvocationsCreateBody()
    const HogFlowsInvocationsCreateParams = orvalSchemas.HogFlowsInvocationsCreateParams()
    return HogFlowsInvocationsCreateParams.omit({ project_id: true }).extend(HogFlowsInvocationsCreateBody.shape)
}

const workflowsTestRun = (): ToolBase<ReturnType<typeof WorkflowsTestRunSchema>, unknown> => ({
    name: 'workflows-test-run',
    schema: WorkflowsTestRunSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsTestRunSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.globals !== undefined) {
            body['globals'] = params.globals
        }
        if (params.mock_async_functions !== undefined) {
            body['mock_async_functions'] = params.mock_async_functions
        }
        if (params.current_action_id !== undefined) {
            body['current_action_id'] = params.current_action_id
        }
        if (params.use_draft !== undefined) {
            body['use_draft'] = params.use_draft
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocations/`,
            body,
        })
        return result
    },
})

const WorkflowsUpdateSchema = () => {
    const HogFlowsPartialUpdateBody = orvalSchemas.HogFlowsPartialUpdateBody()
    const HogFlowsPartialUpdateParams = orvalSchemas.HogFlowsPartialUpdateParams()
    return HogFlowsPartialUpdateParams.omit({ project_id: true }).extend(HogFlowsPartialUpdateBody.shape)
}

const workflowsUpdate = (): ToolBase<ReturnType<typeof WorkflowsUpdateSchema>, WithPostHogUrl<Schemas.HogFlowUpdate>> =>
    withUiApp('workflow', {
        name: 'workflows-update',
        schema: WorkflowsUpdateSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsUpdateSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.trigger_masking !== undefined) {
                body['trigger_masking'] = params.trigger_masking
            }
            if (params.conversion !== undefined) {
                body['conversion'] = params.conversion
            }
            if (params.exit_condition !== undefined) {
                body['exit_condition'] = params.exit_condition
            }
            if (params.email_sending_rate_limit !== undefined) {
                body['email_sending_rate_limit'] = params.email_sending_rate_limit
            }
            if (params.variables !== undefined) {
                body['variables'] = params.variables
            }
            const result = await context.api.request<Schemas.HogFlowUpdate>({
                method: 'PATCH',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/workflows/${result.id}/workflow`)
        },
    })

const WorkflowsUpdateScheduleSchema = () => {
    const HogFlowsSchedulesPartialUpdateBody = orvalSchemas.HogFlowsSchedulesPartialUpdateBody()
    const HogFlowsSchedulesPartialUpdateParams = orvalSchemas.HogFlowsSchedulesPartialUpdateParams()
    return HogFlowsSchedulesPartialUpdateParams.omit({ project_id: true }).extend(
        HogFlowsSchedulesPartialUpdateBody.shape
    )
}

const workflowsUpdateSchedule = (): ToolBase<
    ReturnType<typeof WorkflowsUpdateScheduleSchema>,
    Schemas.HogFlowSchedule
> => ({
    name: 'workflows-update-schedule',
    schema: WorkflowsUpdateScheduleSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsUpdateScheduleSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.rrule !== undefined) {
            body['rrule'] = params.rrule
        }
        if (params.starts_at !== undefined) {
            body['starts_at'] = params.starts_at
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.variables !== undefined) {
            body['variables'] = params.variables
        }
        const result = await context.api.request<Schemas.HogFlowSchedule>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/schedules/${encodeURIComponent(String(params.schedule_id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-create': workflowsCreate,
    'workflows-discard-draft': workflowsDiscardDraft,
    'workflows-get': workflowsGet,
    'workflows-get-invocation': workflowsGetInvocation,
    'workflows-get-revision': workflowsGetRevision,
    'workflows-global-stats': workflowsGlobalStats,
    'workflows-list': workflowsList,
    'workflows-list-batch-jobs': workflowsListBatchJobs,
    'workflows-list-invocations': workflowsListInvocations,
    'workflows-list-proposals': workflowsListProposals,
    'workflows-list-revisions': workflowsListRevisions,
    'workflows-logs': workflowsLogs,
    'workflows-patch-action-email': workflowsPatchActionEmail,
    'workflows-patch-graph': workflowsPatchGraph,
    'workflows-publish': workflowsPublish,
    'workflows-restore-revision': workflowsRestoreRevision,
    'workflows-stats': workflowsStats,
    'workflows-suggest': workflowsSuggest,
    'workflows-test-run': workflowsTestRun,
    'workflows-update': workflowsUpdate,
    'workflows-update-schedule': workflowsUpdateSchedule,
}
