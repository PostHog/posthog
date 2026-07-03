// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    TaskAutomationsCreateBody,
    TaskAutomationsDestroyParams,
    TaskAutomationsListQueryParams,
    TaskAutomationsPartialUpdateBody,
    TaskAutomationsPartialUpdateParams,
    TaskAutomationsRetrieveParams,
    TaskAutomationsRunCreateParams,
    TasksListQueryParams,
    TasksRetrieveParams,
    TasksRunsListParams,
    TasksRunsListQueryParams,
    TasksRunsRetrieveParams,
    TasksRunsSessionLogsRetrieveParams,
    TasksRunsSessionLogsRetrieveQueryParams,
} from '@/generated/tasks/api'
import { withPostHogUrl, pickResponseFields, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TasksListSchema = TasksListQueryParams

const tasksList = (): ToolBase<typeof TasksListSchema, WithPostHogUrl<Schemas.PaginatedTaskDetailDTOList>> => ({
    name: 'tasks-list',
    schema: TasksListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskDetailDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            query: {
                archived: params.archived,
                created_by: params.created_by,
                internal: params.internal,
                limit: params.limit,
                offset: params.offset,
                organization: params.organization,
                origin_product: params.origin_product,
                repository: params.repository,
                search: params.search,
                stage: params.stage,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'task_number',
                    'title',
                    'description',
                    'origin_product',
                    'repository',
                    'internal',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/tasks/${item.id}`))
                ),
            },
            '/tasks'
        )
    },
})

const TasksRetrieveSchema = TasksRetrieveParams.omit({ project_id: true })

const tasksRetrieve = (): ToolBase<typeof TasksRetrieveSchema, WithPostHogUrl<Schemas.TaskDetailDTO>> => ({
    name: 'tasks-retrieve',
    schema: TasksRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskDetailDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'latest_run.log_url',
            'latest_run.state.sandbox_connect_token',
            'latest_run.state.sandbox_url',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksRunsListSchema = TasksRunsListParams.omit({ project_id: true }).extend(TasksRunsListQueryParams.shape)

const tasksRunsList = (): ToolBase<
    typeof TasksRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedTaskRunDetailDTOList>
> => ({
    name: 'tasks-runs-list',
    schema: TasksRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskRunDetailDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'task',
                    'stage',
                    'branch',
                    'status',
                    'environment',
                    'error_message',
                    'state.sandbox_environment_id',
                    'created_at',
                    'updated_at',
                    'completed_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/tasks')
    },
})

const TasksRunsRetrieveSchema = TasksRunsRetrieveParams.omit({ project_id: true })

const tasksRunsRetrieve = (): ToolBase<typeof TasksRunsRetrieveSchema, Schemas.TaskRunDetailDTO> => ({
    name: 'tasks-runs-retrieve',
    schema: TasksRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunDetailDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'log_url',
            'state.sandbox_connect_token',
            'state.sandbox_url',
        ]) as typeof result
        return filtered
    },
})

const TasksRunsSessionLogsRetrieveSchema = TasksRunsSessionLogsRetrieveParams.omit({ project_id: true })
    .extend(TasksRunsSessionLogsRetrieveQueryParams.shape)
    .extend({
        limit: TasksRunsSessionLogsRetrieveQueryParams.shape['limit']
            .default(100)
            .optional()
            .describe('Maximum number of entries to return (default 100, max 5000)'),
    })

const tasksRunsSessionLogsRetrieve = (): ToolBase<typeof TasksRunsSessionLogsRetrieveSchema, unknown> => ({
    name: 'tasks-runs-session-logs-retrieve',
    schema: TasksRunsSessionLogsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsSessionLogsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/session_logs/`,
            query: {
                after: params.after,
                event_types: params.event_types,
                exclude_types: params.exclude_types,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const TaskAutomationsListSchema = TaskAutomationsListQueryParams

const taskAutomationsList = (): ToolBase<
    typeof TaskAutomationsListSchema,
    Schemas.PaginatedTaskAutomationDTOList
> => ({
    name: 'task-automations-list',
    schema: TaskAutomationsListSchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskAutomationDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const TaskAutomationsCreateSchema = TaskAutomationsCreateBody

const taskAutomationsCreate = (): ToolBase<typeof TaskAutomationsCreateSchema, Schemas.TaskAutomationDTO> => ({
    name: 'task-automations-create',
    schema: TaskAutomationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.github_integration !== undefined) {
            body['github_integration'] = params.github_integration
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.TaskAutomationDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/`,
            body,
        })
        return result
    },
})

const TaskAutomationsRetrieveSchema = TaskAutomationsRetrieveParams.omit({ project_id: true })

const taskAutomationsRetrieve = (): ToolBase<typeof TaskAutomationsRetrieveSchema, Schemas.TaskAutomationDTO> => ({
    name: 'task-automations-retrieve',
    schema: TaskAutomationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskAutomationDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const TaskAutomationsPartialUpdateSchema = TaskAutomationsPartialUpdateParams.omit({ project_id: true }).extend(
    TaskAutomationsPartialUpdateBody.shape
)

const taskAutomationsPartialUpdate = (): ToolBase<
    typeof TaskAutomationsPartialUpdateSchema,
    Schemas.TaskAutomationDTO
> => ({
    name: 'task-automations-partial-update',
    schema: TaskAutomationsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.github_integration !== undefined) {
            body['github_integration'] = params.github_integration
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.TaskAutomationDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const TaskAutomationsDestroySchema = TaskAutomationsDestroyParams.omit({ project_id: true })

const taskAutomationsDestroy = (): ToolBase<typeof TaskAutomationsDestroySchema, unknown> => ({
    name: 'task-automations-destroy',
    schema: TaskAutomationsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const TaskAutomationsRunCreateSchema = TaskAutomationsRunCreateParams.omit({ project_id: true })

const taskAutomationsRunCreate = (): ToolBase<typeof TaskAutomationsRunCreateSchema, Schemas.TaskAutomationDTO> => ({
    name: 'task-automations-run-create',
    schema: TaskAutomationsRunCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TaskAutomationsRunCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskAutomationDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_automations/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'tasks-list': tasksList,
    'tasks-retrieve': tasksRetrieve,
    'tasks-runs-list': tasksRunsList,
    'tasks-runs-retrieve': tasksRunsRetrieve,
    'tasks-runs-session-logs-retrieve': tasksRunsSessionLogsRetrieve,
    'task-automations-list': taskAutomationsList,
    'task-automations-create': taskAutomationsCreate,
    'task-automations-retrieve': taskAutomationsRetrieve,
    'task-automations-partial-update': taskAutomationsPartialUpdate,
    'task-automations-destroy': taskAutomationsDestroy,
    'task-automations-run-create': taskAutomationsRunCreate,
}
