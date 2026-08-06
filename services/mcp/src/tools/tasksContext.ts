import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

export const TASKS_CONTEXT_TOOL_NAMES = [
    'tasks-artifacts-list',
    'tasks-artifacts-versions-list',
    'tasks-artifacts-retrieve',
    'tasks-comments-list',
    'tasks-comments-retrieve',
] as const

async function requestTaskResource<TResult>(
    context: Context,
    path: string,
    query?: Record<string, string | number | boolean | undefined>
): Promise<TResult> {
    if (!context.api.config.taskId) {
        throw new Error('Task comments are available only inside the current PostHog Code task.')
    }
    const projectId = await context.stateManager.getProjectId()
    return await context.api.request<TResult>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(context.api.config.taskId)}/${path}`,
        query,
    })
}

const artifactsSchema = z.object({})
const artifactVersionsSchema = z.object({
    artifact_id: z.string().uuid().describe('Stable artifact id returned by tasks-artifacts-list.'),
    limit: z.number().int().min(1).max(100).default(100).describe('Maximum versions to return.'),
    before_version: z.number().int().min(2).optional().describe('Cursor returned by the previous page.'),
})
const artifactRetrieveSchema = z.object({
    artifact_id: z.string().uuid().describe('Stable artifact id returned by tasks-artifacts-list.'),
    version_id: z.string().uuid().optional().describe('Version id to read. Defaults to the current version.'),
    content_offset: z.number().int().min(0).default(0).describe('UTF-8 byte offset for the next content chunk.'),
})
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

export const tasksArtifactVersionsList = (): ToolBase<
    typeof artifactVersionsSchema,
    Schemas.TaskArtifactVersionsResponse
> => ({
    name: 'tasks-artifacts-versions-list',
    schema: artifactVersionsSchema,
    handler: async (context, params) =>
        await requestTaskResource(context, `artifacts/${params.artifact_id}/versions/`, {
            limit: params.limit,
            before_version: params.before_version,
        }),
})

export const tasksArtifactRetrieve = (): ToolBase<
    typeof artifactRetrieveSchema,
    Schemas.TaskArtifactVersionContent
> => ({
    name: 'tasks-artifacts-retrieve',
    schema: artifactRetrieveSchema,
    handler: async (context, params) =>
        await requestTaskResource(
            context,
            `artifacts/${params.artifact_id}/versions/${params.version_id ?? 'current'}/`,
            { content_offset: params.content_offset }
        ),
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
