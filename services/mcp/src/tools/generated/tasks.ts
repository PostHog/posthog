// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LoopsCreateBody,
    LoopsDestroyParams,
    LoopsListQueryParams,
    LoopsPartialUpdateBody,
    LoopsPartialUpdateParams,
    LoopsRetrieveParams,
    LoopsRunCreateParams,
    TasksCreateBody,
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

const LoopsCreateSchema = LoopsCreateBody

const loopsCreate = (): ToolBase<typeof LoopsCreateSchema, Schemas.LoopDTO> => ({
    name: 'loops-create',
    schema: LoopsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LoopsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.visibility !== undefined) {
            body['visibility'] = params.visibility
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
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
        if (params.repositories !== undefined) {
            body['repositories'] = params.repositories
        }
        if (params.sandbox_environment !== undefined) {
            body['sandbox_environment'] = params.sandbox_environment
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.overlap_policy !== undefined) {
            body['overlap_policy'] = params.overlap_policy
        }
        if (params.behaviors !== undefined) {
            body['behaviors'] = params.behaviors
        }
        if (params.connectors !== undefined) {
            body['connectors'] = params.connectors
        }
        if (params.notifications !== undefined) {
            body['notifications'] = params.notifications
        }
        if (params.triggers !== undefined) {
            body['triggers'] = params.triggers
        }
        const result = await context.api.request<Schemas.LoopDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/`,
            body,
        })
        return result
    },
})

const LoopsDestroySchema = LoopsDestroyParams.omit({ project_id: true })

const loopsDestroy = (): ToolBase<typeof LoopsDestroySchema, unknown> => ({
    name: 'loops-destroy',
    schema: LoopsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof LoopsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LoopsListSchema = LoopsListQueryParams

const loopsList = (): ToolBase<typeof LoopsListSchema, WithPostHogUrl<Schemas.PaginatedLoopDTOList>> => ({
    name: 'loops-list',
    schema: LoopsListSchema,
    handler: async (context: Context, params: z.infer<typeof LoopsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLoopDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/tasks')
    },
})

const LoopsPartialUpdateSchema = LoopsPartialUpdateParams.omit({ project_id: true }).extend(
    LoopsPartialUpdateBody.shape
)

const loopsPartialUpdate = (): ToolBase<typeof LoopsPartialUpdateSchema, Schemas.LoopDTO> => ({
    name: 'loops-partial-update',
    schema: LoopsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LoopsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.visibility !== undefined) {
            body['visibility'] = params.visibility
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
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
        if (params.repositories !== undefined) {
            body['repositories'] = params.repositories
        }
        if (params.sandbox_environment !== undefined) {
            body['sandbox_environment'] = params.sandbox_environment
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.overlap_policy !== undefined) {
            body['overlap_policy'] = params.overlap_policy
        }
        if (params.behaviors !== undefined) {
            body['behaviors'] = params.behaviors
        }
        if (params.connectors !== undefined) {
            body['connectors'] = params.connectors
        }
        if (params.notifications !== undefined) {
            body['notifications'] = params.notifications
        }
        if (params.triggers !== undefined) {
            body['triggers'] = params.triggers
        }
        const result = await context.api.request<Schemas.LoopDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const LoopsRetrieveSchema = LoopsRetrieveParams.omit({ project_id: true })

const loopsRetrieve = (): ToolBase<typeof LoopsRetrieveSchema, WithPostHogUrl<Schemas.LoopDTO>> => ({
    name: 'loops-retrieve',
    schema: LoopsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof LoopsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LoopDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/tasks/${result.id}`)
    },
})

const LoopsRunCreateSchema = LoopsRunCreateParams.omit({ project_id: true })

const loopsRunCreate = (): ToolBase<typeof LoopsRunCreateSchema, Schemas.LoopFireResult> => ({
    name: 'loops-run-create',
    schema: LoopsRunCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LoopsRunCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LoopFireResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/loops/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

const TasksCreateSchema = TasksCreateBody.omit({
    title_manually_set: true,
    origin_product: true,
    github_integration: true,
    github_user_integration: true,
    signal_report: true,
    signal_report_task_relationship: true,
    json_schema: true,
    internal: true,
    archived: true,
    ci_prompt: true,
    branch: true,
    runtime_adapter: true,
    model: true,
    reasoning_effort: true,
    pending_user_message: true,
    pending_user_artifact_ids: true,
    auto_publish: true,
    channel: true,
    sandbox_environment_id: true,
    custom_image_id: true,
    runtime: true,
}).extend({
    description: TasksCreateBody.shape['description']
        .unwrap()
        .describe(
            'The task for the agent to carry out, written as a direct prompt (e.g. "Investigate the spike in $exception events on the checkout page and open a PR with a fix"). Passed verbatim to the agent as its instructions, so be specific.'
        ),
})

const tasksCreate = (): ToolBase<typeof TasksCreateSchema, WithPostHogUrl<Schemas.TaskDetailDTO>> => ({
    name: 'tasks-create',
    schema: TasksCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TasksCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        const result = await context.api.request<Schemas.TaskDetailDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'task_number',
            'title',
            'description',
            'origin_product',
            'repository',
            'internal',
            'created_at',
            'updated_at',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

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
                all_team_tasks: params.all_team_tasks,
                archived: params.archived,
                channel: params.channel,
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'loops-create': loopsCreate,
    'loops-destroy': loopsDestroy,
    'loops-list': loopsList,
    'loops-partial-update': loopsPartialUpdate,
    'loops-retrieve': loopsRetrieve,
    'loops-run-create': loopsRunCreate,
    'tasks-create': tasksCreate,
    'tasks-list': tasksList,
    'tasks-retrieve': tasksRetrieve,
    'tasks-runs-list': tasksRunsList,
    'tasks-runs-retrieve': tasksRunsRetrieve,
    'tasks-runs-session-logs-retrieve': tasksRunsSessionLogsRetrieve,
}
