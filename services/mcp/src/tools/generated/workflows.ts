// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFlowsBulkDeleteCreateBody,
    HogFlowsCreateBody,
    HogFlowsDestroyParams,
    HogFlowsListQueryParams,
    HogFlowsPartialUpdateBody,
    HogFlowsPartialUpdateParams,
    HogFlowsRetrieveParams,
} from '@/generated/workflows/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsListSchema = HogFlowsListQueryParams

const workflowsList = (): ToolBase<
    typeof WorkflowsListSchema,
    Schemas.PaginatedHogFlowMinimalList & { _posthogUrl: string }
> => ({
    name: 'workflows-list',
    schema: WorkflowsListSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFlowMinimalList>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_flows/`,
            query: {
                created_at: params.created_at,
                created_by: params.created_by,
                id: params.id,
                limit: params.limit,
                offset: params.offset,
                updated_at: params.updated_at,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/workflows`,
        }
    },
})

const WorkflowsGetSchema = HogFlowsRetrieveParams.omit({ project_id: true })

const workflowsGet = (): ToolBase<typeof WorkflowsGetSchema, Schemas.HogFlow> => ({
    name: 'workflows-get',
    schema: WorkflowsGetSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_flows/${params.id}/`,
        })
        return result
    },
})

const WorkflowsCreateSchema = HogFlowsCreateBody

const workflowsCreate = (): ToolBase<typeof WorkflowsCreateSchema, Schemas.HogFlow & { _posthogUrl: string }> => ({
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
            path: `/api/projects/${projectId}/hog_flows/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/workflows/${(result as any).id}`,
        }
    },
})

const WorkflowsPartialUpdateSchema = HogFlowsPartialUpdateParams.omit({ project_id: true }).extend(
    HogFlowsPartialUpdateBody.shape
)

const workflowsPartialUpdate = (): ToolBase<
    typeof WorkflowsPartialUpdateSchema,
    Schemas.HogFlow & { _posthogUrl: string }
> => ({
    name: 'workflows-partial-update',
    schema: WorkflowsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsPartialUpdateSchema>) => {
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
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_flows/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/workflows/${(result as any).id}`,
        }
    },
})

const WorkflowsBulkDeleteSchema = HogFlowsBulkDeleteCreateBody

const workflowsBulkDelete = (): ToolBase<typeof WorkflowsBulkDeleteSchema, Schemas.HogFlowBulkDeleteResponse> => ({
    name: 'workflows-bulk-delete',
    schema: WorkflowsBulkDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsBulkDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.HogFlowBulkDeleteResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/hog_flows/bulk_delete/`,
            body,
        })
        return result
    },
})

const WorkflowsDestroySchema = HogFlowsDestroyParams.omit({ project_id: true })

const workflowsDestroy = (): ToolBase<typeof WorkflowsDestroySchema, unknown> => ({
    name: 'workflows-destroy',
    schema: WorkflowsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${projectId}/hog_flows/${params.id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-list': workflowsList,
    'workflows-get': workflowsGet,
    'workflows-create': workflowsCreate,
    'workflows-partial-update': workflowsPartialUpdate,
    'workflows-bulk-delete': workflowsBulkDelete,
    'workflows-destroy': workflowsDestroy,
}
