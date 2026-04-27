// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SandboxListQueryParams,
    SandboxRetrieveParams,
    TasksCreateBody,
    TasksDestroyParams,
    TasksListQueryParams,
    TasksPartialUpdateBody,
    TasksPartialUpdateParams,
    TasksRetrieveParams,
    TasksRunCreateBody,
    TasksRunCreateParams,
    TasksRunsListParams,
    TasksRunsListQueryParams,
    TasksRunsRetrieveParams,
    TasksRunsSessionLogsRetrieveParams,
    TasksRunsSessionLogsRetrieveQueryParams,
} from '@/generated/tasks/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TasksListSchema = TasksListQueryParams

const tasksList = (): ToolBase<typeof TasksListSchema, WithPostHogUrl<Schemas.PaginatedTaskList>> => ({
    name: 'tasks-list',
    schema: TasksListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            query: {
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

const tasksRetrieve = (): ToolBase<typeof TasksRetrieveSchema, WithPostHogUrl<Schemas.Task>> => ({
    name: 'tasks-retrieve',
    schema: TasksRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Task>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/tasks/${result.id}`)
    },
})

const TasksCreateSchema = TasksCreateBody

const tasksCreate = (): ToolBase<typeof TasksCreateSchema, WithPostHogUrl<Schemas.Task>> => ({
    name: 'tasks-create',
    schema: TasksCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TasksCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.title_manually_set !== undefined) {
            body['title_manually_set'] = params.title_manually_set
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.origin_product !== undefined) {
            body['origin_product'] = params.origin_product
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.github_integration !== undefined) {
            body['github_integration'] = params.github_integration
        }
        if (params.signal_report !== undefined) {
            body['signal_report'] = params.signal_report
        }
        if (params.signal_report_task_relationship !== undefined) {
            body['signal_report_task_relationship'] = params.signal_report_task_relationship
        }
        if (params.json_schema !== undefined) {
            body['json_schema'] = params.json_schema
        }
        if (params.internal !== undefined) {
            body['internal'] = params.internal
        }
        if (params.ci_prompt !== undefined) {
            body['ci_prompt'] = params.ci_prompt
        }
        const result = await context.api.request<Schemas.Task>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            body,
        })
        return await withPostHogUrl(context, result, `/tasks/${result.id}`)
    },
})

const TasksPartialUpdateSchema = TasksPartialUpdateParams.omit({ project_id: true }).extend(
    TasksPartialUpdateBody.shape
)

const tasksPartialUpdate = (): ToolBase<typeof TasksPartialUpdateSchema, WithPostHogUrl<Schemas.Task>> => ({
    name: 'tasks-partial-update',
    schema: TasksPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof TasksPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.title_manually_set !== undefined) {
            body['title_manually_set'] = params.title_manually_set
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.origin_product !== undefined) {
            body['origin_product'] = params.origin_product
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.github_integration !== undefined) {
            body['github_integration'] = params.github_integration
        }
        if (params.signal_report !== undefined) {
            body['signal_report'] = params.signal_report
        }
        if (params.signal_report_task_relationship !== undefined) {
            body['signal_report_task_relationship'] = params.signal_report_task_relationship
        }
        if (params.json_schema !== undefined) {
            body['json_schema'] = params.json_schema
        }
        if (params.internal !== undefined) {
            body['internal'] = params.internal
        }
        if (params.ci_prompt !== undefined) {
            body['ci_prompt'] = params.ci_prompt
        }
        const result = await context.api.request<Schemas.Task>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/tasks/${result.id}`)
    },
})

const TasksDestroySchema = TasksDestroyParams.omit({ project_id: true })

const tasksDestroy = (): ToolBase<typeof TasksDestroySchema, unknown> => ({
    name: 'tasks-destroy',
    schema: TasksDestroySchema,
    handler: async (context: Context, params: z.infer<typeof TasksDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const TasksRunCreateSchema = z.intersection(
    TasksRunCreateParams.omit({ project_id: true }).passthrough(),
    z.union(
        TasksRunCreateBody.options.map((s: any) => {
            const keys = new Set(Object.keys(s.shape))
            const omit = Object.fromEntries(
                [
                    ['pending_user_artifact_ids', true],
                    ['run_source', true],
                    ['signal_report_id', true],
                    ['github_user_token', true],
                ].filter(([k]) => keys.has(k as string))
            )
            return (Object.keys(omit).length > 0 ? s.omit(omit) : s).passthrough()
        }) as [z.ZodTypeAny, z.ZodTypeAny, ...z.ZodTypeAny[]]
    )
)

const tasksRunCreate = (): ToolBase<typeof TasksRunCreateSchema, WithPostHogUrl<Schemas.Task>> => ({
    name: 'tasks-run-create',
    schema: TasksRunCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        if (params.branch !== undefined) {
            body['branch'] = params.branch
        }
        if (params.resume_from_run_id !== undefined) {
            body['resume_from_run_id'] = params.resume_from_run_id
        }
        if (params.pending_user_message !== undefined) {
            body['pending_user_message'] = params.pending_user_message
        }
        if (params.sandbox_environment_id !== undefined) {
            body['sandbox_environment_id'] = params.sandbox_environment_id
        }
        if (params.pr_authorship_mode !== undefined) {
            body['pr_authorship_mode'] = params.pr_authorship_mode
        }
        if (params.runtime_adapter !== undefined) {
            body['runtime_adapter'] = params.runtime_adapter
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.reasoning_effort !== undefined) {
            body['reasoning_effort'] = params.reasoning_effort
        }
        if (params.initial_permission_mode !== undefined) {
            body['initial_permission_mode'] = params.initial_permission_mode
        }
        const result = await context.api.request<Schemas.Task>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/run/`,
            body,
        })
        const filtered = pickResponseFields(result, ['id', 'title', 'latest_run']) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksRunsListSchema = TasksRunsListParams.omit({ project_id: true }).extend(TasksRunsListQueryParams.shape)

const tasksRunsList = (): ToolBase<typeof TasksRunsListSchema, WithPostHogUrl<Schemas.PaginatedTaskRunDetailList>> => ({
    name: 'tasks-runs-list',
    schema: TasksRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskRunDetailList>({
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

const tasksRunsRetrieve = (): ToolBase<typeof TasksRunsRetrieveSchema, Schemas.TaskRunDetail> => ({
    name: 'tasks-runs-retrieve',
    schema: TasksRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const TasksRunsSessionLogsRetrieveSchema = TasksRunsSessionLogsRetrieveParams.omit({ project_id: true })
    .extend(TasksRunsSessionLogsRetrieveQueryParams.shape)
    .extend({ limit: TasksRunsSessionLogsRetrieveQueryParams.shape['limit'].default(100).optional() })

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

const SandboxListSchema = SandboxListQueryParams

const sandboxList = (): ToolBase<
    typeof SandboxListSchema,
    WithPostHogUrl<Schemas.PaginatedSandboxEnvironmentListList>
> => ({
    name: 'sandbox-list',
    schema: SandboxListSchema,
    handler: async (context: Context, params: z.infer<typeof SandboxListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSandboxEnvironmentListList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/sandbox_environments/`,
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
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/tasks/${item.id}`))
                ),
            },
            '/tasks'
        )
    },
})

const SandboxRetrieveSchema = SandboxRetrieveParams.omit({ project_id: true })

const sandboxRetrieve = (): ToolBase<typeof SandboxRetrieveSchema, Schemas.SandboxEnvironment> => ({
    name: 'sandbox-retrieve',
    schema: SandboxRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SandboxRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SandboxEnvironment>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/sandbox_environments/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'tasks-list': tasksList,
    'tasks-retrieve': tasksRetrieve,
    'tasks-create': tasksCreate,
    'tasks-partial-update': tasksPartialUpdate,
    'tasks-destroy': tasksDestroy,
    'tasks-run-create': tasksRunCreate,
    'tasks-runs-list': tasksRunsList,
    'tasks-runs-retrieve': tasksRunsRetrieve,
    'tasks-runs-session-logs-retrieve': tasksRunsSessionLogsRetrieve,
    'sandbox-list': sandboxList,
    'sandbox-retrieve': sandboxRetrieve,
}
