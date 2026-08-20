import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { TasksListQueryParams } from '@/generated/tasks/api'
import { omitResponseFields, pickResponseFields, withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

export const TASKS_CONTEXT_TOOL_NAMES = [
    'tasks-artifacts-list',
    'tasks-comments-list',
    'tasks-comments-retrieve',
    'tasks-current-retrieve',
] as const

async function requestTaskResource<TResult>(
    context: Context,
    path: string,
    query?: Record<string, string | number | boolean | undefined>
): Promise<TResult> {
    if (!context.api.config.taskId) {
        throw new Error('Task comments are available only inside the current PostHog Desktop task.')
    }
    const projectId = await context.stateManager.getProjectId()
    return await context.api.request<TResult>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(context.api.config.taskId)}/${path}`,
        query,
    })
}

const artifactsSchema = z.object({})
const commentsListSchema = z.object({
    artifact_id: z.string().min(1).optional().describe('Optional artifact id returned by tasks-artifacts-list.'),
    include_resolved: z.boolean().default(false).describe('Include resolved comments. Defaults to false.'),
    limit: z.number().int().min(1).max(100).default(50).describe('Maximum root comments to return. Defaults to 50.'),
    cursor: z.string().min(1).max(256).optional().describe('Opaque cursor returned by a previous call.'),
})
const commentsRetrieveSchema = z.object({
    root_comment_id: z.string().uuid().describe('Root comment id returned by tasks-comments-list.'),
    limit: z.number().int().min(1).max(100).default(50).describe('Maximum comments to return. Defaults to 50.'),
    cursor: z.string().min(1).max(256).optional().describe('Opaque cursor returned by a previous call.'),
    comment_id: z.string().uuid().optional().describe('Comment id whose truncated body should continue.'),
    content_offset: z
        .number()
        .int()
        .min(0)
        .optional()
        .describe('Byte offset returned in content_next_offset for the selected comment.'),
})

export const tasksArtifactsList = (): ToolBase<typeof artifactsSchema, Schemas.TaskArtifactsResponse> => ({
    name: 'tasks-artifacts-list',
    schema: artifactsSchema,
    handler: async (context) => await requestTaskResource(context, 'artifacts/'),
})

export const tasksCommentsList = (): ToolBase<typeof commentsListSchema, Schemas.TaskCommentsResponse> => ({
    name: 'tasks-comments-list',
    schema: commentsListSchema,
    handler: async (context, params) =>
        await requestTaskResource(context, 'comments/', {
            artifact_id: params.artifact_id,
            include_resolved: params.include_resolved,
            limit: params.limit,
            cursor: params.cursor,
        }),
})

const currentRetrieveSchema = z.object({})
const mineListSchema = TasksListQueryParams.pick({
    status: true,
    channel: true,
    search: true,
    repository: true,
    archived: true,
    ordering: true,
    limit: true,
    offset: true,
})

const MINE_LIST_RESULT_FIELDS = [
    'id',
    'task_number',
    'title',
    'description',
    'origin_product',
    'repository',
    'internal',
    'channel',
    'created_by.first_name',
    'created_by.last_name',
    'latest_run.id',
    'latest_run.status',
    'latest_run.environment',
    'created_at',
    'updated_at',
]

export const tasksCurrentRetrieve = (): ToolBase<
    typeof currentRetrieveSchema,
    WithPostHogUrl<Schemas.TaskDetailDTO>
> => ({
    name: 'tasks-current-retrieve',
    schema: currentRetrieveSchema,
    handler: async (context) => {
        const taskId = context.api.config.taskId
        if (!taskId) {
            throw new Error('This tool is available only inside a running task session.')
        }
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskDetailDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(taskId)}/`,
        })
        const filtered = omitResponseFields(result, [
            'latest_run.log_url',
            'latest_run.state.sandbox_connect_token',
            'latest_run.state.sandbox_url',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

export const tasksMineList = (): ToolBase<
    typeof mineListSchema,
    WithPostHogUrl<Schemas.PaginatedTaskDetailDTOList>
> => ({
    name: 'tasks-mine-list',
    schema: mineListSchema,
    handler: async (context, params) => {
        const [projectId, user] = await Promise.all([
            context.stateManager.getProjectId(),
            context.stateManager.getUser(),
        ])
        if (user.id === undefined) {
            throw new Error('Could not resolve the calling user id from the access token.')
        }
        const result = await context.api.request<Schemas.PaginatedTaskDetailDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            query: {
                created_by: user.id,
                archived: params.archived,
                channel: params.channel,
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                repository: params.repository,
                search: params.search,
                status: params.status,
            },
        })
        const currentTaskId = context.api.config.taskId
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item) => ({
                ...pickResponseFields(item, MINE_LIST_RESULT_FIELDS),
                ...(currentTaskId && item.id === currentTaskId ? { is_current_task: true } : {}),
            })),
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

export const tasksCommentsRetrieve = (): ToolBase<typeof commentsRetrieveSchema, Schemas.TaskCommentDetail> => ({
    name: 'tasks-comments-retrieve',
    schema: commentsRetrieveSchema,
    handler: async (context, params) =>
        await requestTaskResource(context, `comments/${params.root_comment_id}/`, {
            limit: params.limit,
            cursor: params.cursor,
            comment_id: params.comment_id,
            content_offset: params.content_offset,
        }),
})
