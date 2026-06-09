// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFlowsBatchJobsListParams,
    HogFlowsCreateBody,
    HogFlowsInvocationsCreateBody,
    HogFlowsInvocationsCreateParams,
    HogFlowsListQueryParams,
    HogFlowsLogsRetrieveParams,
    HogFlowsLogsRetrieveQueryParams,
    HogFlowsMetricsRetrieveParams,
    HogFlowsMetricsRetrieveQueryParams,
    HogFlowsPartialUpdateBody,
    HogFlowsPartialUpdateParams,
    HogFlowsRetrieveParams,
    HogFlowsSchedulesPartialUpdateBody,
    HogFlowsSchedulesPartialUpdateParams,
} from '@/generated/workflows/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HogFlowsLogsRetrieveSchema = HogFlowsLogsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsLogsRetrieveQueryParams.shape
)

const hogFlowsLogsRetrieve = (): ToolBase<typeof HogFlowsLogsRetrieveSchema, unknown> => ({
    name: 'hog-flows-logs-retrieve',
    schema: HogFlowsLogsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFlowsLogsRetrieveSchema>) => {
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

const HogFlowsMetricsRetrieveSchema = HogFlowsMetricsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsMetricsRetrieveQueryParams.shape
)

const hogFlowsMetricsRetrieve = (): ToolBase<typeof HogFlowsMetricsRetrieveSchema, Schemas.AppMetricsResponse> => ({
    name: 'hog-flows-metrics-retrieve',
    schema: HogFlowsMetricsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFlowsMetricsRetrieveSchema>) => {
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
            return await withPostHogUrl(context, result, `/pipeline/destinations/hog-${result.id}`)
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
            return await withPostHogUrl(context, result, `/pipeline/destinations/hog-${result.id}`)
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
            return await withPostHogUrl(context, result, '/pipeline/destinations')
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
        return await withPostHogUrl(context, result, '/pipeline/destinations')
    },
})

const WorkflowsRunSchema = HogFlowsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFlowsInvocationsCreateBody.shape
)

const workflowsRun = (): ToolBase<typeof WorkflowsRunSchema, unknown> => ({
    name: 'workflows-run',
    schema: WorkflowsRunSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsRunSchema>) => {
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
            return await withPostHogUrl(context, result, `/pipeline/destinations/hog-${result.id}`)
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
    'hog-flows-logs-retrieve': hogFlowsLogsRetrieve,
    'hog-flows-metrics-retrieve': hogFlowsMetricsRetrieve,
    'workflows-create': workflowsCreate,
    'workflows-get': workflowsGet,
    'workflows-list': workflowsList,
    'workflows-list-batch-jobs': workflowsListBatchJobs,
    'workflows-run': workflowsRun,
    'workflows-update': workflowsUpdate,
    'workflows-update-schedule': workflowsUpdateSchedule,
}
