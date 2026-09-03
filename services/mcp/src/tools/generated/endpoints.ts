// AUTO-GENERATED from products/endpoints/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/endpoints/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EndpointCreateSchema = () => {
    const EndpointsCreateBody = orvalSchemas.EndpointsCreateBody()
    return EndpointsCreateBody.omit({
        is_active: true,
        derived_from_insight: true,
        version: true,
        bucket_overrides: true,
        deleted: true,
        optional_breakdown_properties: true,
    })
}

const endpointCreate = (): ToolBase<
    ReturnType<typeof EndpointCreateSchema>,
    WithPostHogUrl<Schemas.EndpointResponse>
> => ({
    name: 'endpoint-create',
    schema: EndpointCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointCreateSchema>>) => {
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
        if (params.data_freshness_seconds !== undefined) {
            body['data_freshness_seconds'] = params.data_freshness_seconds
        }
        if (params.is_materialized !== undefined) {
            body['is_materialized'] = params.is_materialized
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointDeleteSchema = () => {
    const EndpointsDestroyParams = orvalSchemas.EndpointsDestroyParams()
    return EndpointsDestroyParams.omit({ project_id: true })
}

const endpointDelete = (): ToolBase<ReturnType<typeof EndpointDeleteSchema>, Schemas.EndpointResponse> => ({
    name: 'endpoint-delete',
    schema: EndpointDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const EndpointGetSchema = () => {
    const EndpointsRetrieveParams = orvalSchemas.EndpointsRetrieveParams()
    return EndpointsRetrieveParams.omit({ project_id: true })
}

const endpointGet = (): ToolBase<
    ReturnType<typeof EndpointGetSchema>,
    WithPostHogUrl<Schemas.EndpointVersionResponse>
> => ({
    name: 'endpoint-get',
    schema: EndpointGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointVersionResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/`,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointLogsSchema = () => {
    const EndpointsLogsRetrieveParams = orvalSchemas.EndpointsLogsRetrieveParams()
    const EndpointsLogsRetrieveQueryParams = orvalSchemas.EndpointsLogsRetrieveQueryParams()
    return EndpointsLogsRetrieveParams.omit({ project_id: true }).extend(EndpointsLogsRetrieveQueryParams.shape)
}

const endpointLogs = (): ToolBase<ReturnType<typeof EndpointLogsSchema>, unknown> => ({
    name: 'endpoint-logs',
    schema: EndpointLogsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointLogsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/logs/`,
            query: {
                after: params.after,
                before: params.before,
                instance_id: params.instance_id,
                level: params.level,
                limit: params.limit,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/endpoints')
    },
})

const EndpointMaterializationConditionsSchema = () => z.object({})

const endpointMaterializationConditions = (): ToolBase<
    ReturnType<typeof EndpointMaterializationConditionsSchema>,
    Schemas.EndpointMaterializationConditions
> => ({
    name: 'endpoint-materialization-conditions',
    schema: EndpointMaterializationConditionsSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof EndpointMaterializationConditionsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointMaterializationConditions>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/materialization_conditions/`,
        })
        return result
    },
})

const EndpointMaterializationStatusSchema = () => {
    const EndpointsMaterializationStatusRetrieveParams = orvalSchemas.EndpointsMaterializationStatusRetrieveParams()
    return EndpointsMaterializationStatusRetrieveParams.omit({ project_id: true })
}

const endpointMaterializationStatus = (): ToolBase<
    ReturnType<typeof EndpointMaterializationStatusSchema>,
    WithPostHogUrl<Schemas.EndpointMaterialization>
> => ({
    name: 'endpoint-materialization-status',
    schema: EndpointMaterializationStatusSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointMaterializationStatusSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EndpointMaterialization>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/materialization_status/`,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointMaterializationSuggestionSchema = () => {
    const EndpointsMaterializationSuggestionCreateBody = orvalSchemas.EndpointsMaterializationSuggestionCreateBody()
    const EndpointsMaterializationSuggestionCreateParams = orvalSchemas.EndpointsMaterializationSuggestionCreateParams()
    return EndpointsMaterializationSuggestionCreateParams.omit({ project_id: true }).extend(
        EndpointsMaterializationSuggestionCreateBody.shape
    )
}

const endpointMaterializationSuggestion = (): ToolBase<
    ReturnType<typeof EndpointMaterializationSuggestionSchema>,
    WithPostHogUrl<Schemas.EndpointMaterializationSuggestion>
> => ({
    name: 'endpoint-materialization-suggestion',
    schema: EndpointMaterializationSuggestionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointMaterializationSuggestionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.version !== undefined) {
            body['version'] = params.version
        }
        const result = await context.api.request<Schemas.EndpointMaterializationSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/materialization_suggestion/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${params.name}`)
    },
})

const EndpointOpenapiSpecSchema = () => {
    const EndpointsOpenapiSpecRetrieveParams = orvalSchemas.EndpointsOpenapiSpecRetrieveParams()
    const EndpointsOpenapiSpecRetrieveQueryParams = orvalSchemas.EndpointsOpenapiSpecRetrieveQueryParams()
    return EndpointsOpenapiSpecRetrieveParams.omit({ project_id: true }).extend(
        EndpointsOpenapiSpecRetrieveQueryParams.shape
    )
}

const endpointOpenapiSpec = (): ToolBase<ReturnType<typeof EndpointOpenapiSpecSchema>, unknown> => ({
    name: 'endpoint-openapi-spec',
    schema: EndpointOpenapiSpecSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointOpenapiSpecSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/openapi.json/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const EndpointRunSchema = () => {
    const EndpointsRunCreateBody = orvalSchemas.EndpointsRunCreateBody()
    const EndpointsRunCreateParams = orvalSchemas.EndpointsRunCreateParams()
    return EndpointsRunCreateParams.omit({ project_id: true })
        .extend(
            EndpointsRunCreateBody.omit({ client_query_id: true, debug: true, filters_override: true, version: true })
                .shape
        )
        .extend({
            variables: EndpointsRunCreateBody.shape['variables'].describe(
                'Key-value pairs to parameterize the query. For HogQL endpoints, keys match variable code_name (e.g. {"event_name": "$pageview"}). For insight endpoints with breakdowns, use the breakdown property name as key.'
            ),
        })
}

const endpointRun = (): ToolBase<
    ReturnType<typeof EndpointRunSchema>,
    WithPostHogUrl<Schemas.EndpointRunResponse>
> => ({
    name: 'endpoint-run',
    schema: EndpointRunSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointRunSchema>>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/run/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointUpdateSchema = () => {
    const EndpointsPartialUpdateBody = orvalSchemas.EndpointsPartialUpdateBody()
    const EndpointsPartialUpdateParams = orvalSchemas.EndpointsPartialUpdateParams()
    return EndpointsPartialUpdateParams.omit({ project_id: true }).extend(
        EndpointsPartialUpdateBody.omit({
            name: true,
            derived_from_insight: true,
            bucket_overrides: true,
            deleted: true,
            optional_breakdown_properties: true,
        }).shape
    )
}

const endpointUpdate = (): ToolBase<
    ReturnType<typeof EndpointUpdateSchema>,
    WithPostHogUrl<Schemas.EndpointResponse>
> => ({
    name: 'endpoint-update',
    schema: EndpointUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.data_freshness_seconds !== undefined) {
            body['data_freshness_seconds'] = params.data_freshness_seconds
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
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.EndpointResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${result.name}`)
    },
})

const EndpointVersionsSchema = () => {
    const EndpointsVersionsListParams = orvalSchemas.EndpointsVersionsListParams()
    const EndpointsVersionsListQueryParams = orvalSchemas.EndpointsVersionsListQueryParams()
    return EndpointsVersionsListParams.omit({ project_id: true }).extend(EndpointsVersionsListQueryParams.shape)
}

const endpointVersions = (): ToolBase<
    ReturnType<typeof EndpointVersionsSchema>,
    WithPostHogUrl<Schemas.PaginatedEndpointVersionResponseList>
> => ({
    name: 'endpoint-versions',
    schema: EndpointVersionsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointVersionsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEndpointVersionResponseList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/versions/`,
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
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/endpoints/${item.name}`))
                ),
            },
            '/endpoints'
        )
    },
})

const EndpointsGetAllSchema = () => {
    const EndpointsListQueryParams = orvalSchemas.EndpointsListQueryParams()
    return EndpointsListQueryParams
}

const endpointsGetAll = (): ToolBase<
    ReturnType<typeof EndpointsGetAllSchema>,
    WithPostHogUrl<Schemas.PaginatedEndpointResponseList>
> => ({
    name: 'endpoints-get-all',
    schema: EndpointsGetAllSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointsGetAllSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedEndpointResponseList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/`,
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
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/endpoints/${item.name}`))
                ),
            },
            '/endpoints'
        )
    },
})

const EndpointsLastExecutionTimesSchema = () => {
    const EndpointsLastExecutionTimesCreateBody = orvalSchemas.EndpointsLastExecutionTimesCreateBody()
    return EndpointsLastExecutionTimesCreateBody
}

const endpointsLastExecutionTimes = (): ToolBase<
    ReturnType<typeof EndpointsLastExecutionTimesSchema>,
    Schemas.QueryStatusResponse
> => ({
    name: 'endpoints-last-execution-times',
    schema: EndpointsLastExecutionTimesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointsLastExecutionTimesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.names !== undefined) {
            body['names'] = params.names
        }
        const result = await context.api.request<Schemas.QueryStatusResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/last_execution_times/`,
            body,
        })
        return result
    },
})

const EndpointsMaterializationPreviewSchema = () => {
    const EndpointsMaterializationPreviewCreateBody = orvalSchemas.EndpointsMaterializationPreviewCreateBody()
    const EndpointsMaterializationPreviewCreateParams = orvalSchemas.EndpointsMaterializationPreviewCreateParams()
    return EndpointsMaterializationPreviewCreateParams.omit({ project_id: true }).extend(
        EndpointsMaterializationPreviewCreateBody.shape
    )
}

const endpointsMaterializationPreview = (): ToolBase<
    ReturnType<typeof EndpointsMaterializationPreviewSchema>,
    unknown
> => ({
    name: 'endpoints-materialization-preview',
    schema: EndpointsMaterializationPreviewSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EndpointsMaterializationPreviewSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.version !== undefined) {
            body['version'] = params.version
        }
        if (params.bucket_overrides !== undefined) {
            body['bucket_overrides'] = params.bucket_overrides
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/endpoints/${encodeURIComponent(String(params.name))}/materialization_preview/`,
            body,
        })
        return await withPostHogUrl(context, result, `/endpoints/${params.name}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'endpoint-create': endpointCreate,
    'endpoint-delete': endpointDelete,
    'endpoint-get': endpointGet,
    'endpoint-logs': endpointLogs,
    'endpoint-materialization-conditions': endpointMaterializationConditions,
    'endpoint-materialization-status': endpointMaterializationStatus,
    'endpoint-materialization-suggestion': endpointMaterializationSuggestion,
    'endpoint-openapi-spec': endpointOpenapiSpec,
    'endpoint-run': endpointRun,
    'endpoint-update': endpointUpdate,
    'endpoint-versions': endpointVersions,
    'endpoints-get-all': endpointsGetAll,
    'endpoints-last-execution-times': endpointsLastExecutionTimes,
    'endpoints-materialization-preview': endpointsMaterializationPreview,
}
