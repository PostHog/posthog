// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    TasksListQueryParams,
    TasksRepositoryReadinessRetrieveQueryParams,
    TasksRetrieveParams,
    TasksRunsListParams,
    TasksRunsListQueryParams,
    TasksRunsRetrieveParams,
} from '@/generated/tasks/api'
import { TaskCreateToolInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TasksListSchema = TasksListQueryParams

const tasksList = (): ToolBase<typeof TasksListSchema, Schemas.PaginatedProjectTaskList & { _posthogUrl: string }> => ({
    name: 'tasks-list',
    schema: TasksListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedProjectTaskList>({
            method: 'GET',
            path: `/api/projects/${projectId}/tasks/`,
            query: {
                created_by: params.created_by,
                limit: params.limit,
                offset: params.offset,
                organization: params.organization,
                origin_product: params.origin_product,
                repository: params.repository,
                stage: params.stage,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/tasks`,
        }
    },
})

const TaskCreateSchema = TaskCreateToolInputSchema

const taskCreate = (): ToolBase<typeof TaskCreateSchema> => ({
    name: 'task-create',
    schema: TaskCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TaskCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const { run_immediately = true, run_mode = 'background', run_branch, ...body } = params
        const result = await context.api.request({
            method: 'POST',
            path: `/api/projects/${projectId}/tasks/`,
            body,
        })
        if (run_immediately !== false) {
            const postActionBody: Record<string, unknown> = {}
            if (run_mode !== undefined) {
                postActionBody['mode'] = run_mode
            }
            if (run_branch !== undefined) {
                postActionBody['branch'] = run_branch
            }
            const postActionResult = await context.api.request({
                method: 'POST',
                path: `/api/projects/${projectId}/tasks/${(result as any).id}/run/`,
                body: postActionBody,
            })
            return {
                ...(postActionResult as any),
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/tasks/${(postActionResult as any).id}`,
            }
        }
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/tasks/${(result as any).id}`,
        }
    },
})

const TaskGetSchema = TasksRetrieveParams.omit({ project_id: true })

const taskGet = (): ToolBase<typeof TaskGetSchema, Schemas.ProjectTask & { _posthogUrl: string }> => ({
    name: 'task-get',
    schema: TaskGetSchema,
    handler: async (context: Context, params: z.infer<typeof TaskGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ProjectTask>({
            method: 'GET',
            path: `/api/projects/${projectId}/tasks/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/tasks/${(result as any).id}`,
        }
    },
})

const TaskRunsListSchema = TasksRunsListParams.omit({ project_id: true }).extend(TasksRunsListQueryParams.shape)

const taskRunsList = (): ToolBase<
    typeof TaskRunsListSchema,
    Schemas.PaginatedTaskRunDetailList & { _posthogUrl: string }
> => ({
    name: 'task-runs-list',
    schema: TaskRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof TaskRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskRunDetailList>({
            method: 'GET',
            path: `/api/projects/${projectId}/tasks/${params.task_id}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/tasks`,
        }
    },
})

const TaskRunGetSchema = TasksRunsRetrieveParams.omit({ project_id: true })

const taskRunGet = (): ToolBase<typeof TaskRunGetSchema, Schemas.TaskRunDetail> => ({
    name: 'task-run-get',
    schema: TaskRunGetSchema,
    handler: async (context: Context, params: z.infer<typeof TaskRunGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunDetail>({
            method: 'GET',
            path: `/api/projects/${projectId}/tasks/${params.task_id}/runs/${params.id}/`,
        })
        return result
    },
})

const TaskRepositoryReadinessGetSchema = TasksRepositoryReadinessRetrieveQueryParams

const taskRepositoryReadinessGet = (): ToolBase<
    typeof TaskRepositoryReadinessGetSchema,
    Schemas.RepositoryReadinessResponse
> => ({
    name: 'task-repository-readiness-get',
    schema: TaskRepositoryReadinessGetSchema,
    handler: async (context: Context, params: z.infer<typeof TaskRepositoryReadinessGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RepositoryReadinessResponse>({
            method: 'GET',
            path: `/api/projects/${projectId}/tasks/repository_readiness/`,
            query: {
                refresh: params.refresh,
                repository: params.repository,
                window_days: params.window_days,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'tasks-list': tasksList,
    'task-create': taskCreate,
    'task-get': taskGet,
    'task-runs-list': taskRunsList,
    'task-run-get': taskRunGet,
    'task-repository-readiness-get': taskRepositoryReadinessGet,
}
