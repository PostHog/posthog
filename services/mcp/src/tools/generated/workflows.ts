// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFlowsBatchJobsListParams,
    HogFlowsCreateBody,
    HogFlowsInvocationResultRetrieveParams,
    HogFlowsInvocationResultsRetrieveParams,
    HogFlowsInvocationResultsRetrieveQueryParams,
    HogFlowsInvocationsCreateBody,
    HogFlowsInvocationsCreateParams,
    HogFlowsListQueryParams,
    HogFlowsLogsRetrieveParams,
    HogFlowsLogsRetrieveQueryParams,
    HogFlowsMetricsGlobalRetrieveQueryParams,
    HogFlowsMetricsRetrieveParams,
    HogFlowsMetricsRetrieveQueryParams,
    HogFlowsPartialUpdateBody,
    HogFlowsPartialUpdateParams,
    HogFlowsRetrieveParams,
    HogFlowsSchedulesPartialUpdateBody,
    HogFlowsSchedulesPartialUpdateParams,
} from '@/generated/workflows/api'
import { withUiApp } from '@/resources/ui-apps'
import { WorkflowGraphPatchSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsCreateSchema = HogFlowsCreateBody

const workflowsCreate = (): ToolBase<typeof WorkflowsCreateSchema, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-create',
        schema: WorkflowsCreateSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsCreateSchema>) => {
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
            if (params.trigger_masking !== undefined) {
                body['trigger_masking'] = params.trigger_masking
            }
            if (params.conversion !== undefined) {
                body['conversion'] = params.conversion
            }
            if (params.exit_condition !== undefined) {
                body['exit_condition'] = params.exit_condition
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

const WorkflowsGetSchema = HogFlowsRetrieveParams.omit({ project_id: true })

const workflowsGet = (): ToolBase<typeof WorkflowsGetSchema, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-get',
        schema: WorkflowsGetSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.HogFlow>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/workflows/${result.id}/workflow`)
        },
    })

const WorkflowsGetInvocationSchema = HogFlowsInvocationResultRetrieveParams.omit({ project_id: true })

const workflowsGetInvocation = (): ToolBase<
    typeof WorkflowsGetInvocationSchema,
    Schemas.HogInvocationResultDetail
> => ({
    name: 'workflows-get-invocation',
    schema: WorkflowsGetInvocationSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGetInvocationSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogInvocationResultDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocation_results/${encodeURIComponent(String(params.invocation_id))}/`,
        })
        return result
    },
})

const WorkflowsGlobalStatsSchema = HogFlowsMetricsGlobalRetrieveQueryParams

const workflowsGlobalStats = (): ToolBase<
    typeof WorkflowsGlobalStatsSchema,
    WithPostHogUrl<Schemas.WorkflowStatsRow[]>
> => ({
    name: 'workflows-global-stats',
    schema: WorkflowsGlobalStatsSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGlobalStatsSchema>) => {
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

const WorkflowsListSchema = HogFlowsListQueryParams

const workflowsList = (): ToolBase<typeof WorkflowsListSchema, WithPostHogUrl<Schemas.PaginatedHogFlowMinimalList>> =>
    withUiApp('workflow-list', {
        name: 'workflows-list',
        schema: WorkflowsListSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsListSchema>) => {
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
                    status: params.status,
                    updated_at: params.updated_at,
                },
            })
            return await withPostHogUrl(context, result, '/workflows')
        },
    })

const WorkflowsListBatchJobsSchema = HogFlowsBatchJobsListParams.omit({ project_id: true })

const workflowsListBatchJobs = (): ToolBase<
    typeof WorkflowsListBatchJobsSchema,
    WithPostHogUrl<Schemas.HogFlowBatchJob[]>
> => ({
    name: 'workflows-list-batch-jobs',
    schema: WorkflowsListBatchJobsSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListBatchJobsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFlowBatchJob[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/batch_jobs/`,
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsListInvocationsSchema = HogFlowsInvocationResultsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsInvocationResultsRetrieveQueryParams.shape
)

const workflowsListInvocations = (): ToolBase<
    typeof WorkflowsListInvocationsSchema,
    WithPostHogUrl<Schemas.HogInvocationResult[]>
> => ({
    name: 'workflows-list-invocations',
    schema: WorkflowsListInvocationsSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListInvocationsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogInvocationResult[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocation_results/`,
            query: {
                after: params.after,
                before: params.before,
                distinct_id: params.distinct_id,
                limit: params.limit,
                status: params.status,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const WorkflowsLogsSchema = HogFlowsLogsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsLogsRetrieveQueryParams.shape
)

const workflowsLogs = (): ToolBase<typeof WorkflowsLogsSchema, unknown> => ({
    name: 'workflows-logs',
    schema: WorkflowsLogsSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsLogsSchema>) => {
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

const WorkflowsPatchGraphSchema = WorkflowGraphPatchSchema

const workflowsPatchGraph = (): ToolBase<typeof WorkflowsPatchGraphSchema, Schemas.HogFlow> => ({
    name: 'workflows-patch-graph',
    schema: WorkflowsPatchGraphSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsPatchGraphSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = WorkflowsPatchGraphSchema.parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(id))}/graph/`,
            body,
        })
        return result
    },
})

const WorkflowsStatsSchema = HogFlowsMetricsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsMetricsRetrieveQueryParams.shape
)

const workflowsStats = (): ToolBase<typeof WorkflowsStatsSchema, Schemas.AppMetricsResponse> => ({
    name: 'workflows-stats',
    schema: WorkflowsStatsSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsStatsSchema>) => {
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
            },
        })
        return result
    },
})

const WorkflowsTestRunSchema = HogFlowsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFlowsInvocationsCreateBody.shape
)

const workflowsTestRun = (): ToolBase<typeof WorkflowsTestRunSchema, unknown> => ({
    name: 'workflows-test-run',
    schema: WorkflowsTestRunSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsTestRunSchema>) => {
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/invocations/`,
            body,
        })
        return result
    },
})

const WorkflowsUpdateSchema = HogFlowsPartialUpdateParams.omit({ project_id: true }).extend(
    HogFlowsPartialUpdateBody.shape
)

const workflowsUpdate = (): ToolBase<typeof WorkflowsUpdateSchema, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-update',
        schema: WorkflowsUpdateSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsUpdateSchema>) => {
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
                method: 'PATCH',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/workflows/${result.id}/workflow`)
        },
    })

const WorkflowsUpdateScheduleSchema = HogFlowsSchedulesPartialUpdateParams.omit({ project_id: true }).extend(
    HogFlowsSchedulesPartialUpdateBody.shape
)

const workflowsUpdateSchedule = (): ToolBase<typeof WorkflowsUpdateScheduleSchema, Schemas.HogFlowSchedule> => ({
    name: 'workflows-update-schedule',
    schema: WorkflowsUpdateScheduleSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsUpdateScheduleSchema>) => {
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
    'workflows-get': workflowsGet,
    'workflows-get-invocation': workflowsGetInvocation,
    'workflows-global-stats': workflowsGlobalStats,
    'workflows-list': workflowsList,
    'workflows-list-batch-jobs': workflowsListBatchJobs,
    'workflows-list-invocations': workflowsListInvocations,
    'workflows-logs': workflowsLogs,
    'workflows-patch-graph': workflowsPatchGraph,
    'workflows-stats': workflowsStats,
    'workflows-test-run': workflowsTestRun,
    'workflows-update': workflowsUpdate,
    'workflows-update-schedule': workflowsUpdateSchedule,
}
