// AUTO-GENERATED from products/actions/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ActionsCreateBody,
    ActionsDestroyParams,
    ActionsListQueryParams,
    ActionsPartialUpdateBody,
    ActionsPartialUpdateParams,
    ActionsRetrieveParams,
} from '@/generated/actions/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ActionsGetAllSchema = ActionsListQueryParams.omit({ format: true })

const actionsGetAll = (): ToolBase<typeof ActionsGetAllSchema, unknown> => ({
    name: 'actions-get-all',
    schema: ActionsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof ActionsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedActionList>({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${item.id}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/action-list.html',
        },
    },
})

const ActionCreateSchema = ActionsCreateBody.omit({ _create_in_folder: true })

const actionCreate = (): ToolBase<typeof ActionCreateSchema, Schemas.Action & { _posthogUrl: string }> => ({
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
        const result = await context.api.request<Schemas.Action>({
            method: 'POST',
            path: `/api/projects/${projectId}/actions/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/action.html',
        },
    },
})

const ActionGetSchema = ActionsRetrieveParams.omit({ project_id: true })

const actionGet = (): ToolBase<typeof ActionGetSchema, Schemas.Action & { _posthogUrl: string }> => ({
    name: 'action-get',
    schema: ActionGetSchema,
    handler: async (context: Context, params: z.infer<typeof ActionGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Action>({
            method: 'GET',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/action.html',
        },
    },
})

const ActionUpdateSchema = ActionsPartialUpdateParams.omit({ project_id: true }).extend(
    ActionsPartialUpdateBody.omit({ _create_in_folder: true }).shape
)

const actionUpdate = (): ToolBase<typeof ActionUpdateSchema, Schemas.Action & { _posthogUrl: string }> => ({
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
        const result = await context.api.request<Schemas.Action>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/action.html',
        },
    },
})

const ActionDeleteSchema = ActionsDestroyParams.omit({ project_id: true })

const actionDelete = (): ToolBase<typeof ActionDeleteSchema, unknown> => ({
    name: 'action-delete',
    schema: ActionDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ActionDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/actions/${params.id}/`,
            body: { deleted: true },
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
