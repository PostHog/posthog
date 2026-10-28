// AUTO-GENERATED from products/warehouse_sources/mcp/warehouse_destinations.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/warehouse_destinations/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ExternalDataDestinationsAddSourcesSchema = () => {
    const ExternalDataDestinationsAddSourcesCreateBody = orvalSchemas.ExternalDataDestinationsAddSourcesCreateBody()
    const ExternalDataDestinationsAddSourcesCreateParams = orvalSchemas.ExternalDataDestinationsAddSourcesCreateParams()
    return ExternalDataDestinationsAddSourcesCreateParams.omit({ project_id: true }).extend(
        ExternalDataDestinationsAddSourcesCreateBody.shape
    )
}

const externalDataDestinationsAddSources = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsAddSourcesSchema>,
    WithPostHogUrl<Schemas.AddSourcesResponse>
> => ({
    name: 'external-data-destinations-add-sources',
    schema: ExternalDataDestinationsAddSourcesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsAddSourcesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_ids !== undefined) {
            body['source_ids'] = params.source_ids
        }
        if (params.resync !== undefined) {
            body['resync'] = params.resync
        }
        const result = await context.api.request<Schemas.AddSourcesResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/${encodeURIComponent(String(params.id))}/add_sources/`,
            body,
        })
        return await withPostHogUrl(context, result, `/data-management/warehouse-destinations?destination=${params.id}`)
    },
})

const ExternalDataDestinationsConnectLinkSchema = () => {
    const ExternalDataDestinationsConnectLinkRetrieveQueryParams =
        orvalSchemas.ExternalDataDestinationsConnectLinkRetrieveQueryParams()
    return ExternalDataDestinationsConnectLinkRetrieveQueryParams
}

const externalDataDestinationsConnectLink = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsConnectLinkSchema>,
    Schemas.DestinationConnectLink
> => ({
    name: 'external-data-destinations-connect-link',
    schema: ExternalDataDestinationsConnectLinkSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataDestinationsConnectLinkSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DestinationConnectLink>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/connect_link/`,
            query: {
                destination_type: params.destination_type,
                integration_kind: params.integration_kind,
            },
        })
        return result
    },
})

const ExternalDataDestinationsCreateSchema = () => {
    const ExternalDataDestinationsCreateBody = orvalSchemas.ExternalDataDestinationsCreateBody()
    return ExternalDataDestinationsCreateBody
}

const externalDataDestinationsCreate = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsCreateSchema>,
    WithPostHogUrl<Schemas.ExternalDataDestination>
> => ({
    name: 'external-data-destinations-create',
    schema: ExternalDataDestinationsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.integration !== undefined) {
            body['integration'] = params.integration
        }
        const result = await context.api.request<Schemas.ExternalDataDestination>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/`,
            body,
        })
        return await withPostHogUrl(context, result, `/data-management/warehouse-destinations?destination=${result.id}`)
    },
})

const ExternalDataDestinationsListSchema = () => {
    const ExternalDataDestinationsListQueryParams = orvalSchemas.ExternalDataDestinationsListQueryParams()
    return ExternalDataDestinationsListQueryParams
}

const externalDataDestinationsList = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsListSchema>,
    Schemas.PaginatedExternalDataDestinationList
> => ({
    name: 'external-data-destinations-list',
    schema: ExternalDataDestinationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExternalDataDestinationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ExternalDataDestinationsRetrieveSchema = () => {
    const ExternalDataDestinationsRetrieveParams = orvalSchemas.ExternalDataDestinationsRetrieveParams()
    return ExternalDataDestinationsRetrieveParams.omit({ project_id: true })
}

const externalDataDestinationsRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsRetrieveSchema>,
    WithPostHogUrl<Schemas.ExternalDataDestination>
> => ({
    name: 'external-data-destinations-retrieve',
    schema: ExternalDataDestinationsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataDestination>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/data-management/warehouse-destinations?destination=${result.id}`)
    },
})

const ExternalDataDestinationsTestConnectionSchema = () => {
    const ExternalDataDestinationsTestConnectionCreateParams =
        orvalSchemas.ExternalDataDestinationsTestConnectionCreateParams()
    return ExternalDataDestinationsTestConnectionCreateParams.omit({ project_id: true })
}

const externalDataDestinationsTestConnection = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsTestConnectionSchema>,
    Schemas.DestinationConnectionTestResponse
> => ({
    name: 'external-data-destinations-test-connection',
    schema: ExternalDataDestinationsTestConnectionSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataDestinationsTestConnectionSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DestinationConnectionTestResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/${encodeURIComponent(String(params.id))}/test_connection/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'external-data-destinations-add-sources': externalDataDestinationsAddSources,
    'external-data-destinations-connect-link': externalDataDestinationsConnectLink,
    'external-data-destinations-create': externalDataDestinationsCreate,
    'external-data-destinations-list': externalDataDestinationsList,
    'external-data-destinations-retrieve': externalDataDestinationsRetrieve,
    'external-data-destinations-test-connection': externalDataDestinationsTestConnection,
}
