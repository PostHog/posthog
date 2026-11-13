// AUTO-GENERATED from products/warehouse_sources/mcp/warehouse_destinations.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/warehouse_destinations/api'
import { normalizeParamAliases } from '@/tools/cast-helpers'
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
                migration_item_id: params.migration_item_id,
            },
        })
        return result
    },
})

const ExternalDataDestinationsConnectLinkStatusSchema = () => {
    const ExternalDataDestinationsConnectLinkStatusRetrieveQueryParams =
        orvalSchemas.ExternalDataDestinationsConnectLinkStatusRetrieveQueryParams()
    return ExternalDataDestinationsConnectLinkStatusRetrieveQueryParams
}

const externalDataDestinationsConnectLinkStatus = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsConnectLinkStatusSchema>,
    Schemas.DestinationConnectStatus
> => ({
    name: 'external-data-destinations-connect-link-status',
    schema: ExternalDataDestinationsConnectLinkStatusSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataDestinationsConnectLinkStatusSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DestinationConnectStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/connect_link_status/`,
            query: {
                connect_token: params.connect_token,
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
        if (params.migration_item_id !== undefined) {
            body['migration_item_id'] = params.migration_item_id
        }
        const result = await context.api.request<Schemas.ExternalDataDestination>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/`,
            body,
        })
        return await withPostHogUrl(context, result, `/data-management/warehouse-destinations?destination=${result.id}`)
    },
})

const ExternalDataDestinationsDeleteSchema = () => {
    const ExternalDataDestinationsDestroyParams = orvalSchemas.ExternalDataDestinationsDestroyParams()
    return ExternalDataDestinationsDestroyParams.omit({ project_id: true })
}

const externalDataDestinationsDelete = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsDeleteSchema>,
    unknown
> => ({
    name: 'external-data-destinations-delete',
    schema: ExternalDataDestinationsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
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

const ExternalDataDestinationsUpdateSchema = () => {
    const ExternalDataDestinationsPartialUpdateBody = orvalSchemas.ExternalDataDestinationsPartialUpdateBody()
    const ExternalDataDestinationsPartialUpdateParams = orvalSchemas.ExternalDataDestinationsPartialUpdateParams()
    return ExternalDataDestinationsPartialUpdateParams.omit({ project_id: true }).extend(
        ExternalDataDestinationsPartialUpdateBody.shape
    )
}

const externalDataDestinationsUpdate = (): ToolBase<
    ReturnType<typeof ExternalDataDestinationsUpdateSchema>,
    WithPostHogUrl<Schemas.ExternalDataDestination>
> => ({
    name: 'external-data-destinations-update',
    schema: ExternalDataDestinationsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataDestinationsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.ExternalDataDestination>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_destinations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/data-management/warehouse-destinations?destination=${result.id}`)
    },
})

const ExternalDataSchemasDestinationsUpdateSchema = () => {
    const ExternalDataSchemasDestinationsPartialUpdateBody =
        orvalSchemas.ExternalDataSchemasDestinationsPartialUpdateBody()
    const ExternalDataSchemasDestinationsPartialUpdateParams =
        orvalSchemas.ExternalDataSchemasDestinationsPartialUpdateParams()
    return z.preprocess(
        normalizeParamAliases({ id: ['schema_id', 'schemaId'] }),
        ExternalDataSchemasDestinationsPartialUpdateParams.omit({ project_id: true })
            .extend(ExternalDataSchemasDestinationsPartialUpdateBody.shape)
            .extend({
                destination_ids: ExternalDataSchemasDestinationsPartialUpdateBody.shape['destination_ids'].describe(
                    'The full list of destination ids for this table, at least one, at most 10. Pass null to remove the override so the table follows its source again.'
                ),
            })
    )
}

const externalDataSchemasDestinationsUpdate = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasDestinationsUpdateSchema>,
    Schemas.SchemaDestinations
> => ({
    name: 'external-data-schemas-destinations-update',
    schema: ExternalDataSchemasDestinationsUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSchemasDestinationsUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.destination_ids !== undefined) {
            body['destination_ids'] = params.destination_ids
        }
        const result = await context.api.request<Schemas.SchemaDestinations>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/destinations/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'external-data-destinations-add-sources': externalDataDestinationsAddSources,
    'external-data-destinations-connect-link': externalDataDestinationsConnectLink,
    'external-data-destinations-connect-link-status': externalDataDestinationsConnectLinkStatus,
    'external-data-destinations-create': externalDataDestinationsCreate,
    'external-data-destinations-delete': externalDataDestinationsDelete,
    'external-data-destinations-list': externalDataDestinationsList,
    'external-data-destinations-retrieve': externalDataDestinationsRetrieve,
    'external-data-destinations-test-connection': externalDataDestinationsTestConnection,
    'external-data-destinations-update': externalDataDestinationsUpdate,
    'external-data-schemas-destinations-update': externalDataSchemasDestinationsUpdate,
}
