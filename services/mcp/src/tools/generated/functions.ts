// AUTO-GENERATED from products/cdp/mcp/functions.yaml + OpenAPI — do not edit
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
} from '@/generated/functions/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FunctionsListSchema = HogFunctionsListQueryParams

const functionsList = (): ToolBase<
    typeof FunctionsListSchema,
    Schemas.PaginatedHogFunctionMinimalList & { _posthogUrl: string }
> => ({
    name: 'functions-list',
    schema: FunctionsListSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsListSchema>) => {
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

const FunctionsCreateSchema = HogFunctionsCreateBody.omit({ _create_in_folder: true })

const functionsCreate = (): ToolBase<typeof FunctionsCreateSchema, Schemas.HogFunction> => ({
    name: 'functions-create',
    schema: FunctionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsCreateSchema>) => {
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

const FunctionsRetrieveSchema = HogFunctionsRetrieveParams.omit({ project_id: true })

const functionsRetrieve = (): ToolBase<typeof FunctionsRetrieveSchema, Schemas.HogFunction> => ({
    name: 'functions-retrieve',
    schema: FunctionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
        })
        return result
    },
})

const FunctionsPartialUpdateSchema = HogFunctionsPartialUpdateParams.omit({ project_id: true }).extend(
    HogFunctionsPartialUpdateBody.omit({ deleted: true, _create_in_folder: true }).shape
)

const functionsPartialUpdate = (): ToolBase<typeof FunctionsPartialUpdateSchema, Schemas.HogFunction> => ({
    name: 'functions-partial-update',
    schema: FunctionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsPartialUpdateSchema>) => {
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

const FunctionsDeleteSchema = HogFunctionsDestroyParams.omit({ project_id: true })

const functionsDelete = (): ToolBase<typeof FunctionsDeleteSchema, unknown> => ({
    name: 'functions-delete',
    schema: FunctionsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/hog_functions/${params.id}/`,
            body: { deleted: true },
        })
        return result
    },
})

const FunctionsInvocationsCreateSchema = HogFunctionsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFunctionsInvocationsCreateBody.shape
)

const functionsInvocationsCreate = (): ToolBase<
    typeof FunctionsInvocationsCreateSchema,
    Schemas.HogFunctionInvocation
> => ({
    name: 'functions-invocations-create',
    schema: FunctionsInvocationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsInvocationsCreateSchema>) => {
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

const FunctionsRearrangePartialUpdateSchema = HogFunctionsRearrangePartialUpdateBody

const functionsRearrangePartialUpdate = (): ToolBase<typeof FunctionsRearrangePartialUpdateSchema, unknown> => ({
    name: 'functions-rearrange-partial-update',
    schema: FunctionsRearrangePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionsRearrangePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.orders !== undefined) {
            body['orders'] = params.orders
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
    'functions-list': functionsList,
    'functions-create': functionsCreate,
    'functions-retrieve': functionsRetrieve,
    'functions-partial-update': functionsPartialUpdate,
    'functions-delete': functionsDelete,
    'functions-invocations-create': functionsInvocationsCreate,
    'functions-rearrange-partial-update': functionsRearrangePartialUpdate,
}
