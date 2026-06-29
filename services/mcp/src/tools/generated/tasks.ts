// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    TasksListQueryParams,
    TasksRetrieveParams,
    TasksRunsListParams,
    TasksRunsListQueryParams,
    TasksRunsLivingArtifactsCreateBody,
    TasksRunsLivingArtifactsCreateParams,
    TasksRunsLivingArtifactsEditBody,
    TasksRunsLivingArtifactsEditParams,
    TasksRunsLivingArtifactsListParams,
    TasksRunsLivingArtifactsOpenParams,
    TasksRunsLivingArtifactsSendParams,
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

const TasksRunsLivingArtifactsCreateSchema = TasksRunsLivingArtifactsCreateParams.omit({ project_id: true }).extend(
    TasksRunsLivingArtifactsCreateBody.shape
)

const tasksRunsLivingArtifactsCreate = (): ToolBase<
    typeof TasksRunsLivingArtifactsCreateSchema,
    Schemas.TaskRunLivingArtifactResponse
> => ({
    name: 'tasks-runs-living-artifacts-create',
    schema: TasksRunsLivingArtifactsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsLivingArtifactsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.artifact_type !== undefined) {
            body['artifact_type'] = params.artifact_type
        }
        if (params.adapter !== undefined) {
            body['adapter'] = params.adapter
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.content_base64 !== undefined) {
            body['content_base64'] = params.content_base64
        }
        if (params.content_type !== undefined) {
            body['content_type'] = params.content_type
        }
        if (params.source_artifact_id !== undefined) {
            body['source_artifact_id'] = params.source_artifact_id
        }
        if (params.source_storage_path !== undefined) {
            body['source_storage_path'] = params.source_storage_path
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.slack_delivery_mode !== undefined) {
            body['slack_delivery_mode'] = params.slack_delivery_mode
        }
        if (params.slack_channel_id !== undefined) {
            body['slack_channel_id'] = params.slack_channel_id
        }
        if (params.slack_thread_ts !== undefined) {
            body['slack_thread_ts'] = params.slack_thread_ts
        }
        const result = await context.api.request<Schemas.TaskRunLivingArtifactResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/living_artifacts/`,
            body,
        })
        return result
    },
})

const TasksRunsLivingArtifactsEditSchema = TasksRunsLivingArtifactsEditParams.omit({ project_id: true }).extend(
    TasksRunsLivingArtifactsEditBody.shape
)

const tasksRunsLivingArtifactsEdit = (): ToolBase<
    typeof TasksRunsLivingArtifactsEditSchema,
    Schemas.TaskRunLivingArtifactResponse
> => ({
    name: 'tasks-runs-living-artifacts-edit',
    schema: TasksRunsLivingArtifactsEditSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsLivingArtifactsEditSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.content_base64 !== undefined) {
            body['content_base64'] = params.content_base64
        }
        if (params.content_type !== undefined) {
            body['content_type'] = params.content_type
        }
        if (params.source_artifact_id !== undefined) {
            body['source_artifact_id'] = params.source_artifact_id
        }
        if (params.source_storage_path !== undefined) {
            body['source_storage_path'] = params.source_storage_path
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.slack_delivery_mode !== undefined) {
            body['slack_delivery_mode'] = params.slack_delivery_mode
        }
        if (params.slack_channel_id !== undefined) {
            body['slack_channel_id'] = params.slack_channel_id
        }
        if (params.slack_thread_ts !== undefined) {
            body['slack_thread_ts'] = params.slack_thread_ts
        }
        const result = await context.api.request<Schemas.TaskRunLivingArtifactResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/living_artifacts/${encodeURIComponent(String(params.artifact_id))}/edit/`,
            body,
        })
        return result
    },
})

const TasksRunsLivingArtifactsSendSchema = TasksRunsLivingArtifactsSendParams.omit({ project_id: true })

const tasksRunsLivingArtifactsSend = (): ToolBase<
    typeof TasksRunsLivingArtifactsSendSchema,
    Schemas.TaskRunLivingArtifactResponse
> => ({
    name: 'tasks-runs-living-artifacts-send',
    schema: TasksRunsLivingArtifactsSendSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsLivingArtifactsSendSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunLivingArtifactResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/living_artifacts/${encodeURIComponent(String(params.artifact_id))}/send/`,
        })
        return result
    },
})

const TasksRunsLivingArtifactsListSchema = TasksRunsLivingArtifactsListParams.omit({ project_id: true })

const tasksRunsLivingArtifactsList = (): ToolBase<
    typeof TasksRunsLivingArtifactsListSchema,
    WithPostHogUrl<Schemas.TaskRunLivingArtifactsResponse>
> => ({
    name: 'tasks-runs-living-artifacts-list',
    schema: TasksRunsLivingArtifactsListSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsLivingArtifactsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunLivingArtifactsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/living_artifacts/`,
        })
        return await withPostHogUrl(context, result, '/tasks')
    },
})

const TasksRunsLivingArtifactsOpenSchema = TasksRunsLivingArtifactsOpenParams.omit({ project_id: true })

const tasksRunsLivingArtifactsOpen = (): ToolBase<
    typeof TasksRunsLivingArtifactsOpenSchema,
    Schemas.TaskRunLivingArtifactOpenResponse
> => ({
    name: 'tasks-runs-living-artifacts-open',
    schema: TasksRunsLivingArtifactsOpenSchema,
    handler: async (context: Context, params: z.infer<typeof TasksRunsLivingArtifactsOpenSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunLivingArtifactOpenResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/living_artifacts/${encodeURIComponent(String(params.artifact_id))}/`,
        })
        return result
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
    'tasks-list': tasksList,
    'tasks-retrieve': tasksRetrieve,
    'tasks-runs-living-artifacts-create': tasksRunsLivingArtifactsCreate,
    'tasks-runs-living-artifacts-edit': tasksRunsLivingArtifactsEdit,
    'tasks-runs-living-artifacts-send': tasksRunsLivingArtifactsSend,
    'tasks-runs-living-artifacts-list': tasksRunsLivingArtifactsList,
    'tasks-runs-living-artifacts-open': tasksRunsLivingArtifactsOpen,
    'tasks-runs-list': tasksRunsList,
    'tasks-runs-retrieve': tasksRunsRetrieve,
    'tasks-runs-session-logs-retrieve': tasksRunsSessionLogsRetrieve,
}
