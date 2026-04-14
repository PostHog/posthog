// AUTO-GENERATED from products/endpoints/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EndpointsCreateBody,
    EndpointsDestroyParams,
    EndpointsListQueryParams,
    EndpointsMaterializationStatusRetrieveParams,
    EndpointsOpenapiJsonRetrieveParams,
    EndpointsOpenapiJsonRetrieveQueryParams,
    EndpointsPartialUpdateBody,
    EndpointsPartialUpdateParams,
    EndpointsRetrieveParams,
    EndpointsRunCreateBody,
    EndpointsRunCreateParams,
    EndpointsVersionsListParams,
    EndpointsVersionsListQueryParams,
} from '@/generated/endpoints/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EndpointsGetAllSchema = EndpointsListQueryParams

const endpointsGetAll = (): ToolBase<
    typeof EndpointsGetAllSchema,
    WithPostHogUrl<Schemas.PaginatedEndpointResponseList>
> => ({
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
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    result.results.map((item) => withPostHogUrl(context, item, `/endpoints/${item.name}`))
                ),
            },
            '/endpoints'
        )
    },
})

const EndpointGetSchema = EndpointsRetrieveParams.omit({ project_id: true })

const endpointGet = (): ToolBase<typeof EndpointGetSchema, WithPostHogUrl<Schemas.EndpointVersionResponse>> => ({
    name: 'endpoint-get',
    schema: EndpointGetSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointVersionResponse>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
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

const endpointCreate = (): ToolBase<typeof EndpointCreateSchema, WithPostHogUrl<Schemas.EndpointResponse>> => ({
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
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointUpdateSchema = EndpointsPartialUpdateParams.omit({ project_id: true }).extend(
    EndpointsPartialUpdateBody.omit({
        name: true,
        sync_frequency: true,
        derived_from_insight: true,
        bucket_overrides: true,
        deleted: true,
    }).shape
)

const endpointUpdate = (): ToolBase<typeof EndpointUpdateSchema, WithPostHogUrl<Schemas.EndpointResponse>> => ({
    name: 'endpoint-update',
    schema: EndpointUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.cache_age_seconds !== undefined) {
            body['cache_age_seconds'] = params.cache_age_seconds
        }
        if (params.is_active !== undefined) {
            body['is_active'] = params.is_active
        }
        if (params.is_materialized !== undefined) {
            body['is_materialized'] = params.is_materialized
        }
        if (params.version !== undefined) {
            body['version'] = params.version
        }
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointDeleteSchema = EndpointsDestroyParams.omit({ project_id: true })

const endpointDelete = (): ToolBase<typeof EndpointDeleteSchema, Schemas.EndpointResponse> => ({
    name: 'endpoint-delete',
    schema: EndpointDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/endpoints/${params.name}/`,
            body: { deleted: true },
        })
        return result
    },
})

const EndpointRunSchema = EndpointsRunCreateParams.omit({ project_id: true })
    .extend(EndpointsRunCreateBody.omit({ client_query_id: true, debug: true, version: true }).shape)
    .extend({
        variables: EndpointsRunCreateBody.shape['variables'].describe(
            'Key-value pairs to parameterize the query. For HogQL endpoints, keys match variable code_name (e.g. {"event_name": "$pageview"}). For insight endpoints with breakdowns, use the breakdown property name as key.'
        ),
    })

const endpointRun = (): ToolBase<typeof EndpointRunSchema, WithPostHogUrl<Schemas.EndpointRunResponse>> => ({
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
        const result = await context.api.request<Schemas.EndpointRunResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/endpoints/${params.name}/run/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointVersionsSchema = EndpointsVersionsListParams.omit({ project_id: true }).extend(
    EndpointsVersionsListQueryParams.shape
)

const endpointVersions = (): ToolBase<
    typeof EndpointVersionsSchema,
    WithPostHogUrl<Schemas.PaginatedEndpointVersionResponseList>
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
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    result.results.map((item) => withPostHogUrl(context, item, `/endpoints/${item.name}`))
                ),
            },
            '/endpoints'
        )
    },
})

const EndpointMaterializationStatusSchema = EndpointsMaterializationStatusRetrieveParams.omit({ project_id: true })

const endpointMaterializationStatus = (): ToolBase<
    typeof EndpointMaterializationStatusSchema,
    WithPostHogUrl<Schemas.EndpointMaterialization>
> => ({
    name: 'endpoint-materialization-status',
    schema: EndpointMaterializationStatusSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointMaterializationStatusSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointMaterialization>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/materialization_status/`,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointOpenapiSpecSchema = EndpointsOpenapiJsonRetrieveParams.omit({ project_id: true }).extend(
    EndpointsOpenapiJsonRetrieveQueryParams.shape
)

const endpointOpenapiSpec = (): ToolBase<typeof EndpointOpenapiSpecSchema, unknown> => ({
    name: 'endpoint-openapi-spec',
    schema: EndpointOpenapiSpecSchema,
    handler: async (context: Context, params: z.infer<typeof EndpointOpenapiSpecSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/endpoints/${params.name}/openapi.json/`,
            query: {
                version: params.version,
            },
        })
        return result
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
    'endpoint-openapi-spec': endpointOpenapiSpec,
}
