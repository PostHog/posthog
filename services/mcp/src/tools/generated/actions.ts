// AUTO-GENERATED from definitions/actions.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    ActionsCreateBody,
    ActionsDestroyParams,
    ActionsListQueryParams,
    ActionsPartialUpdateBody,
    ActionsPartialUpdateParams,
    ActionsRetrieveParams,
} from '@/generated/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ActionsGetAllSchema = ActionsListQueryParams.omit({ format: true })

const actionsGetAll = (): ToolBase<typeof ActionsGetAllSchema> => ({
    name: 'actions-get-all',
    schema: ActionsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof ActionsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return (items as any[]).map((item: any) => ({
            ...item,
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${item.id}`,
        }))
    },
})

const ActionCreateSchema = ActionsCreateBody.omit({ deleted: true, last_calculated_at: true, _create_in_folder: true })

const actionCreate = (): ToolBase<typeof ActionCreateSchema> => ({
    name: 'action-create',
    schema: ActionCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ActionCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.post_to_slack !== undefined) {
            body['post_to_slack'] = params.post_to_slack
        }
        if (params.slack_message_format !== undefined) {
            body['slack_message_format'] = params.slack_message_format
        }
        if (params.steps !== undefined) {
            body['steps'] = params.steps
        }
        if (params.pinned_at !== undefined) {
            body['pinned_at'] = params.pinned_at
        }
        const result = await context.api.request({
            method: 'POST',
            path: `/api/projects/${projectId}/actions/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionGetSchema = ActionsRetrieveParams.omit({ project_id: true })

const actionGet = (): ToolBase<typeof ActionGetSchema> => ({
    name: 'action-get',
    schema: ActionGetSchema,
    handler: async (context: Context, params: z.infer<typeof ActionGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionUpdateSchema = ActionsPartialUpdateParams.omit({ project_id: true }).merge(
    ActionsPartialUpdateBody.omit({ deleted: true, last_calculated_at: true, _create_in_folder: true })
)

const actionUpdate = (): ToolBase<typeof ActionUpdateSchema> => ({
    name: 'action-update',
    schema: ActionUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ActionUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.post_to_slack !== undefined) {
            body['post_to_slack'] = params.post_to_slack
        }
        if (params.slack_message_format !== undefined) {
            body['slack_message_format'] = params.slack_message_format
        }
        if (params.steps !== undefined) {
            body['steps'] = params.steps
        }
        if (params.pinned_at !== undefined) {
            body['pinned_at'] = params.pinned_at
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
})

const ActionDeleteSchema = ActionsDestroyParams.omit({ project_id: true })

const actionDelete = (): ToolBase<typeof ActionDeleteSchema> => ({
    name: 'action-delete',
    schema: ActionDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ActionDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'DELETE',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'actions-get-all': actionsGetAll,
    'action-create': actionCreate,
    'action-get': actionGet,
    'action-update': actionUpdate,
    'action-delete': actionDelete,
}
