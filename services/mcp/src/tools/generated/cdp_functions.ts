// AUTO-GENERATED from products/cdp/mcp/cdp_functions.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionsCreateBody,
    HogFunctionsDestroyParams,
    HogFunctionsInvocationsCreateBody,
    HogFunctionsInvocationsCreateParams,
    HogFunctionsListQueryParams,
    HogFunctionsPartialUpdateBody,
    HogFunctionsPartialUpdateParams,
    HogFunctionsRearrangePartialUpdateBody,
    HogFunctionsRetrieveParams,
} from '@/generated/cdp_functions/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CdpFunctionsListSchema = HogFunctionsListQueryParams

const cdpFunctionsList = (): ToolBase<
    typeof CdpFunctionsListSchema,
    Schemas.PaginatedHogFunctionMinimalList & { _posthogUrl: string }
> => ({
    name: 'cdp-functions-list',
    schema: CdpFunctionsListSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsListSchema>) => {
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

const CdpFunctionsCreateSchema = HogFunctionsCreateBody

const cdpFunctionsCreate = (): ToolBase<typeof CdpFunctionsCreateSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-create',
    schema: CdpFunctionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsCreateSchema>) => {
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

const CdpFunctionsRetrieveSchema = HogFunctionsRetrieveParams.omit({ project_id: true })

const cdpFunctionsRetrieve = (): ToolBase<typeof CdpFunctionsRetrieveSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-retrieve',
    schema: CdpFunctionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
        })
        return result
    },
})

const CdpFunctionsPartialUpdateSchema = HogFunctionsPartialUpdateParams.omit({ project_id: true }).extend(
    HogFunctionsPartialUpdateBody.shape
)

const cdpFunctionsPartialUpdate = (): ToolBase<typeof CdpFunctionsPartialUpdateSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-partial-update',
    schema: CdpFunctionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsPartialUpdateSchema>) => {
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

const CdpFunctionsDeleteSchema = HogFunctionsDestroyParams.omit({ project_id: true })

const cdpFunctionsDelete = (): ToolBase<typeof CdpFunctionsDeleteSchema, unknown> => ({
    name: 'cdp-functions-delete',
    schema: CdpFunctionsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
            body: { deleted: true },
        })
        return result
    },
})

const CdpFunctionsInvocationsCreateSchema = HogFunctionsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFunctionsInvocationsCreateBody.shape
)

const cdpFunctionsInvocationsCreate = (): ToolBase<
    typeof CdpFunctionsInvocationsCreateSchema,
    Schemas.HogFunctionInvocation
> => ({
    name: 'cdp-functions-invocations-create',
    schema: CdpFunctionsInvocationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsInvocationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.configuration !== undefined) {
            body['configuration'] = params.configuration
        }
        if (params.globals !== undefined) {
            body['globals'] = params.globals
        }
        if (params.clickhouse_event !== undefined) {
            body['clickhouse_event'] = params.clickhouse_event
        }
        if (params.mock_async_functions !== undefined) {
            body['mock_async_functions'] = params.mock_async_functions
        }
        if (params.invocation_id !== undefined) {
            body['invocation_id'] = params.invocation_id
        }
        const result = await context.api.request<Schemas.HogFunctionInvocation>({
            method: 'POST',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/invocations/`,
            body,
        })
        return result
    },
})

const CdpFunctionsRearrangePartialUpdateSchema = HogFunctionsRearrangePartialUpdateBody

const cdpFunctionsRearrangePartialUpdate = (): ToolBase<
    typeof CdpFunctionsRearrangePartialUpdateSchema,
    Schemas.HogFunction[]
> => ({
    name: 'cdp-functions-rearrange-partial-update',
    schema: CdpFunctionsRearrangePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsRearrangePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.orders !== undefined) {
            body['orders'] = params.orders
        }
        const result = await context.api.request<Schemas.HogFunction[]>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_functions/rearrange/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cdp-functions-list': cdpFunctionsList,
    'cdp-functions-create': cdpFunctionsCreate,
    'cdp-functions-retrieve': cdpFunctionsRetrieve,
    'cdp-functions-partial-update': cdpFunctionsPartialUpdate,
    'cdp-functions-delete': cdpFunctionsDelete,
    'cdp-functions-invocations-create': cdpFunctionsInvocationsCreate,
    'cdp-functions-rearrange-partial-update': cdpFunctionsRearrangePartialUpdate,
}
