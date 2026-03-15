// AUTO-GENERATED from products/endpoints/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EndpointsCreateBody,
    EndpointsDestroyParams,
    EndpointsListQueryParams,
    EndpointsMaterializationStatusRetrieveParams,
    EndpointsPartialUpdateParams,
    EndpointsRetrieveParams,
    EndpointsRunCreateBody,
    EndpointsRunCreateParams,
    EndpointsVersionsListParams,
    EndpointsVersionsListQueryParams,
} from '@/generated/endpoints/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EndpointsGetAllSchema = EndpointsListQueryParams

const endpointsGetAll = (): ToolBase<typeof EndpointsGetAllSchema, unknown> => ({
    name: 'endpoints-get-all',
    schema: EndpointsGetAllSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointsGetAllSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEndpointResponseList>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/`,
            query: {
                created_by: params.created_by,
                is_active: params.is_active,
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${item.name}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints`,
        }
    },
})

const EndpointGetSchema = EndpointsRetrieveParams.omit({ project_id: true })

const endpointGet = (): ToolBase<typeof EndpointGetSchema, Schemas.EndpointResponse & { _posthogUrl: string }> => ({
    name: 'endpoint-get',
    schema: EndpointGetSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

const EndpointCreateSchema = EndpointsCreateBody.omit({
    is_active: true,
    sync_frequency: true,
    derived_from_insight: true,
    version: true,
    bucket_overrides: true,
    deleted: true,
})

const endpointCreate = (): ToolBase<
    typeof EndpointCreateSchema,
    Schemas.EndpointResponse & { _posthogUrl: string }
> => ({
    name: 'endpoint-create',
    schema: EndpointCreateSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.cache_age_seconds !== undefined) {
            body['cache_age_seconds'] = params.cache_age_seconds
        }
        if (params.is_materialized !== undefined) {
            body['is_materialized'] = params.is_materialized
        }
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/endpoints/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

const EndpointUpdateSchema = EndpointsPartialUpdateParams.omit({ project_id: true })

const endpointUpdate = (): ToolBase<typeof EndpointUpdateSchema, unknown> => ({
    name: 'endpoint-update',
    schema: EndpointUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

const EndpointDeleteSchema = EndpointsDestroyParams.omit({ project_id: true })

const endpointDelete = (): ToolBase<typeof EndpointDeleteSchema, unknown> => ({
    name: 'endpoint-delete',
    schema: EndpointDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
            body: { deleted: true },
        })
        return result
    },
})

const EndpointRunSchema = EndpointsRunCreateParams.omit({ project_id: true }).extend(
    EndpointsRunCreateBody.omit({ client_query_id: true, debug: true, filters_override: true, version: true }).shape
)

const endpointRun = (): ToolBase<typeof EndpointRunSchema, unknown> => ({
    name: 'endpoint-run',
    schema: EndpointRunSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.limit !== undefined) {
            body['limit'] = params.limit
        }
        if (params.offset !== undefined) {
            body['offset'] = params.offset
        }
        if (params.refresh !== undefined) {
            body['refresh'] = params.refresh
        }
        if (params.variables !== undefined) {
            body['variables'] = params.variables
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/endpoints/${params.name}/run/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

const EndpointVersionsSchema = EndpointsVersionsListParams.omit({ project_id: true }).extend(
    EndpointsVersionsListQueryParams.shape
)

const endpointVersions = (): ToolBase<
    typeof EndpointVersionsSchema,
    Schemas.PaginatedEndpointVersionResponseList & { _posthogUrl: string }
> => ({
    name: 'endpoint-versions',
    schema: EndpointVersionsSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointVersionsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEndpointVersionResponseList>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/versions/`,
            query: {
                created_by: params.created_by,
                is_active: params.is_active,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

const EndpointMaterializationStatusSchema = EndpointsMaterializationStatusRetrieveParams.omit({ project_id: true })

const endpointMaterializationStatus = (): ToolBase<
    typeof EndpointMaterializationStatusSchema,
    Schemas.EndpointMaterialization & { _posthogUrl: string }
> => ({
    name: 'endpoint-materialization-status',
    schema: EndpointMaterializationStatusSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointMaterializationStatusSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointMaterialization>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/materialization_status/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/endpoints/${(result as any).name}`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'endpoints-get-all': endpointsGetAll,
    'endpoint-get': endpointGet,
    'endpoint-create': endpointCreate,
    'endpoint-update': endpointUpdate,
    'endpoint-delete': endpointDelete,
    'endpoint-run': endpointRun,
    'endpoint-versions': endpointVersions,
    'endpoint-materialization-status': endpointMaterializationStatus,
}
