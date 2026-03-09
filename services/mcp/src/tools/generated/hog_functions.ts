// AUTO-GENERATED from products/cdp/mcp/hog_functions.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionsCreateBody,
    HogFunctionsInvocationsCreateBody,
    HogFunctionsInvocationsCreateParams,
    HogFunctionsListQueryParams,
    HogFunctionsPartialUpdateBody,
    HogFunctionsPartialUpdateParams,
    HogFunctionsRearrangePartialUpdateBody,
    HogFunctionsRetrieveParams,
} from '@/generated/hog_functions/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HogFunctionsListSchema = HogFunctionsListQueryParams

const hogFunctionsList = (): ToolBase<
    typeof HogFunctionsListSchema,
    Schemas.PaginatedHogFunctionMinimalList & { _posthogUrl: string }
> => ({
    name: 'hog-functions-list',
    schema: HogFunctionsListSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionMinimalList>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_functions/`,
            query: {
                created_at: params.created_at,
                created_by: params.created_by,
                enabled: params.enabled,
                id: params.id,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                type: params.type,
                updated_at: params.updated_at,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/pipeline`,
        }
    },
})

const HogFunctionsCreateSchema = HogFunctionsCreateBody.omit({ _create_in_folder: true })

const hogFunctionsCreate = (): ToolBase<typeof HogFunctionsCreateSchema, Schemas.HogFunction> => ({
    name: 'hog-functions-create',
    schema: HogFunctionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'POST',
            path: `/api/projects/${projectId}/hog_functions/`,
            body,
        })
        return result
    },
})

const HogFunctionsRetrieveSchema = HogFunctionsRetrieveParams.omit({ project_id: true })

const hogFunctionsRetrieve = (): ToolBase<typeof HogFunctionsRetrieveSchema, Schemas.HogFunction> => ({
    name: 'hog-functions-retrieve',
    schema: HogFunctionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
        })
        return result
    },
})

const HogFunctionsPartialUpdateSchema = HogFunctionsPartialUpdateParams.omit({ project_id: true }).extend(
    HogFunctionsPartialUpdateBody.omit({ _create_in_folder: true }).shape
)

const hogFunctionsPartialUpdate = (): ToolBase<typeof HogFunctionsPartialUpdateSchema, Schemas.HogFunction> => ({
    name: 'hog-functions-partial-update',
    schema: HogFunctionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
            body,
        })
        return result
    },
})

const HogFunctionsInvocationsCreateSchema = HogFunctionsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFunctionsInvocationsCreateBody.omit({ _create_in_folder: true }).shape
)

const hogFunctionsInvocationsCreate = (): ToolBase<typeof HogFunctionsInvocationsCreateSchema, unknown> => ({
    name: 'hog-functions-invocations-create',
    schema: HogFunctionsInvocationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsInvocationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/invocations/`,
            body,
        })
        return result
    },
})

const HogFunctionsRearrangePartialUpdateSchema = HogFunctionsRearrangePartialUpdateBody.omit({
    _create_in_folder: true,
})

const hogFunctionsRearrangePartialUpdate = (): ToolBase<typeof HogFunctionsRearrangePartialUpdateSchema, unknown> => ({
    name: 'hog-functions-rearrange-partial-update',
    schema: HogFunctionsRearrangePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionsRearrangePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_functions/rearrange/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'hog-functions-list': hogFunctionsList,
    'hog-functions-create': hogFunctionsCreate,
    'hog-functions-retrieve': hogFunctionsRetrieve,
    'hog-functions-partial-update': hogFunctionsPartialUpdate,
    'hog-functions-invocations-create': hogFunctionsInvocationsCreate,
    'hog-functions-rearrange-partial-update': hogFunctionsRearrangePartialUpdate,
}
