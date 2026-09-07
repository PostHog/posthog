// AUTO-GENERATED from products/warehouse_sources/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/warehouse_sources/api'
import { ExternalDataSourcePayloadSchema, ExternalDataSourceTypeSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DataWarehouseSourceConnectLinkSchema = () => {
    const ExternalDataSourcesConnectLinkRetrieveQueryParams =
        orvalSchemas.ExternalDataSourcesConnectLinkRetrieveQueryParams()
    return ExternalDataSourcesConnectLinkRetrieveQueryParams.extend({ source_type: ExternalDataSourceTypeSchema })
}

const dataWarehouseSourceConnectLink = (): ToolBase<
    ReturnType<typeof DataWarehouseSourceConnectLinkSchema>,
    Schemas.SourceConnectLink
> => ({
    name: 'data-warehouse-source-connect-link',
    schema: DataWarehouseSourceConnectLinkSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataWarehouseSourceConnectLinkSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SourceConnectLink>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/connect_link/`,
            query: {
                source_type: params.source_type,
            },
        })
        return result
    },
})

const DataWarehouseSourceSetupSchema = () => {
    const ExternalDataSourcesSetupCreateBody = orvalSchemas.ExternalDataSourcesSetupCreateBody()
    return ExternalDataSourcesSetupCreateBody.extend({ source_type: ExternalDataSourceTypeSchema })
}

const dataWarehouseSourceSetup = (): ToolBase<
    ReturnType<typeof DataWarehouseSourceSetupSchema>,
    Schemas.SourceSetupResponse
> => ({
    name: 'data-warehouse-source-setup',
    schema: DataWarehouseSourceSetupSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataWarehouseSourceSetupSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        const result = await context.api.request<Schemas.SourceSetupResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/setup/`,
            body,
        })
        return result
    },
})

const DataWarehouseStoredCredentialsListSchema = () => {
    const ExternalDataSourcesStoredCredentialsListQueryParams =
        orvalSchemas.ExternalDataSourcesStoredCredentialsListQueryParams()
    return ExternalDataSourcesStoredCredentialsListQueryParams
}

const dataWarehouseStoredCredentialsList = (): ToolBase<
    ReturnType<typeof DataWarehouseStoredCredentialsListSchema>,
    WithPostHogUrl<Schemas.SourceCredential[]>
> => ({
    name: 'data-warehouse-stored-credentials-list',
    schema: DataWarehouseStoredCredentialsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataWarehouseStoredCredentialsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SourceCredential[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/stored_credentials/`,
            query: {
                search: params.search,
                source_type: params.source_type,
            },
        })
        return await withPostHogUrl(context, result, '/data-management/sources')
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
        return await withPostHogUrl(context, result, `/data-management/sources/${result.id}`)
    },
})

const ExternalDataSchemasCancelSchema = () => {
    const ExternalDataSchemasCancelCreateParams = orvalSchemas.ExternalDataSchemasCancelCreateParams()
    return ExternalDataSchemasCancelCreateParams.omit({ project_id: true })
}

const externalDataSchemasCancel = (): ToolBase<ReturnType<typeof ExternalDataSchemasCancelSchema>, unknown> => ({
    name: 'external-data-schemas-cancel',
    schema: ExternalDataSchemasCancelSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasCancelSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/cancel/`,
        })
        return result
    },
})

const ExternalDataSchemasDeleteDataSchema = () => {
    const ExternalDataSchemasDeleteDataDestroyParams = orvalSchemas.ExternalDataSchemasDeleteDataDestroyParams()
    return ExternalDataSchemasDeleteDataDestroyParams.omit({ project_id: true })
}

const externalDataSchemasDeleteData = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasDeleteDataSchema>,
    unknown
> => ({
    name: 'external-data-schemas-delete-data',
    schema: ExternalDataSchemasDeleteDataSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasDeleteDataSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/delete_data/`,
        })
        return result
    },
})

const ExternalDataSchemasDestinationsRetrieveSchema = () => {
    const ExternalDataSchemasDestinationsRetrieveParams = orvalSchemas.ExternalDataSchemasDestinationsRetrieveParams()
    return ExternalDataSchemasDestinationsRetrieveParams.omit({ project_id: true })
}

const externalDataSchemasDestinationsRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasDestinationsRetrieveSchema>,
    Schemas.SchemaDestinations
> => ({
    name: 'external-data-schemas-destinations-retrieve',
    schema: ExternalDataSchemasDestinationsRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSchemasDestinationsRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SchemaDestinations>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/destinations/`,
        })
        return result
    },
})

const ExternalDataSchemasIncrementalFieldsCreateSchema = () => {
    const ExternalDataSchemasIncrementalFieldsCreateBody = orvalSchemas.ExternalDataSchemasIncrementalFieldsCreateBody()
    const ExternalDataSchemasIncrementalFieldsCreateParams =
        orvalSchemas.ExternalDataSchemasIncrementalFieldsCreateParams()
    return ExternalDataSchemasIncrementalFieldsCreateParams.omit({ project_id: true }).extend(
        ExternalDataSchemasIncrementalFieldsCreateBody.shape
    )
}

const externalDataSchemasIncrementalFieldsCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasIncrementalFieldsCreateSchema>,
    unknown
> => ({
    name: 'external-data-schemas-incremental-fields-create',
    schema: ExternalDataSchemasIncrementalFieldsCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSchemasIncrementalFieldsCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.should_sync !== undefined) {
            body['should_sync'] = params.should_sync
        }
        if (params.sync_type !== undefined) {
            body['sync_type'] = params.sync_type
        }
        if (params.incremental_field !== undefined) {
            body['incremental_field'] = params.incremental_field
        }
        if (params.incremental_field_type !== undefined) {
            body['incremental_field_type'] = params.incremental_field_type
        }
        if (params.incremental_field_lookback_seconds !== undefined) {
            body['incremental_field_lookback_seconds'] = params.incremental_field_lookback_seconds
        }
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
        }
        if (params.sync_time_of_day !== undefined) {
            body['sync_time_of_day'] = params.sync_time_of_day
        }
        if (params.primary_key_columns !== undefined) {
            body['primary_key_columns'] = params.primary_key_columns
        }
        if (params.cdc_table_mode !== undefined) {
            body['cdc_table_mode'] = params.cdc_table_mode
        }
        if (params.enabled_columns !== undefined) {
            body['enabled_columns'] = params.enabled_columns
        }
        if (params.row_filters !== undefined) {
            body['row_filters'] = params.row_filters
        }
        if (params.api_version !== undefined) {
            body['api_version'] = params.api_version
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/incremental_fields/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasListSchema = () => {
    const ExternalDataSchemasListQueryParams = orvalSchemas.ExternalDataSchemasListQueryParams()
    return ExternalDataSchemasListQueryParams
}

const externalDataSchemasList = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasListSchema>,
    WithPostHogUrl<Schemas.PaginatedExternalDataSchemaList>
> => ({
    name: 'external-data-schemas-list',
    schema: ExternalDataSchemasListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExternalDataSchemaList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['table.columns', 'available_columns'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/data-management/sources')
    },
})

const ExternalDataSchemasPartialUpdateSchema = () => {
    const ExternalDataSchemasPartialUpdateBody = orvalSchemas.ExternalDataSchemasPartialUpdateBody()
    const ExternalDataSchemasPartialUpdateParams = orvalSchemas.ExternalDataSchemasPartialUpdateParams()
    return ExternalDataSchemasPartialUpdateParams.omit({ project_id: true }).extend(
        ExternalDataSchemasPartialUpdateBody.shape
    )
}

const externalDataSchemasPartialUpdate = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasPartialUpdateSchema>,
    Schemas.ExternalDataSchema
> => ({
    name: 'external-data-schemas-partial-update',
    schema: ExternalDataSchemasPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.should_sync !== undefined) {
            body['should_sync'] = params.should_sync
        }
        if (params.sync_type !== undefined) {
            body['sync_type'] = params.sync_type
        }
        if (params.incremental_field !== undefined) {
            body['incremental_field'] = params.incremental_field
        }
        if (params.incremental_field_type !== undefined) {
            body['incremental_field_type'] = params.incremental_field_type
        }
        if (params.incremental_field_lookback_seconds !== undefined) {
            body['incremental_field_lookback_seconds'] = params.incremental_field_lookback_seconds
        }
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
        }
        if (params.sync_time_of_day !== undefined) {
            body['sync_time_of_day'] = params.sync_time_of_day
        }
        if (params.primary_key_columns !== undefined) {
            body['primary_key_columns'] = params.primary_key_columns
        }
        if (params.cdc_table_mode !== undefined) {
            body['cdc_table_mode'] = params.cdc_table_mode
        }
        if (params.enabled_columns !== undefined) {
            body['enabled_columns'] = params.enabled_columns
        }
        if (params.row_filters !== undefined) {
            body['row_filters'] = params.row_filters
        }
        if (params.api_version !== undefined) {
            body['api_version'] = params.api_version
        }
        const result = await context.api.request<Schemas.ExternalDataSchema>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasReloadSchema = () => {
    const ExternalDataSchemasReloadCreateParams = orvalSchemas.ExternalDataSchemasReloadCreateParams()
    return ExternalDataSchemasReloadCreateParams.omit({ project_id: true })
}

const externalDataSchemasReload = (): ToolBase<ReturnType<typeof ExternalDataSchemasReloadSchema>, unknown> => ({
    name: 'external-data-schemas-reload',
    schema: ExternalDataSchemasReloadSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasReloadSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/reload/`,
        })
        return result
    },
})

const ExternalDataSchemasResyncSchema = () => {
    const ExternalDataSchemasResyncCreateParams = orvalSchemas.ExternalDataSchemasResyncCreateParams()
    return ExternalDataSchemasResyncCreateParams.omit({ project_id: true })
}

const externalDataSchemasResync = (): ToolBase<ReturnType<typeof ExternalDataSchemasResyncSchema>, unknown> => ({
    name: 'external-data-schemas-resync',
    schema: ExternalDataSchemasResyncSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasResyncSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/resync/`,
        })
        return result
    },
})

const ExternalDataSchemasRetrieveSchema = () => {
    const ExternalDataSchemasRetrieveParams = orvalSchemas.ExternalDataSchemasRetrieveParams()
    return ExternalDataSchemasRetrieveParams.omit({ project_id: true })
}

const externalDataSchemasRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataSchemasRetrieveSchema>,
    Schemas.ExternalDataSchema
> => ({
    name: 'external-data-schemas-retrieve',
    schema: ExternalDataSchemasRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSchemasRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataSchema>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExternalDataSourcesCheckCdcPrerequisitesCreateSchema = () =>
    z.object({}).extend({ source_type: ExternalDataSourceTypeSchema })

const externalDataSourcesCheckCdcPrerequisitesCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesCheckCdcPrerequisitesCreateSchema>,
    unknown
> => ({
    name: 'external-data-sources-check-cdc-prerequisites-create',
    schema: ExternalDataSourcesCheckCdcPrerequisitesCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesCheckCdcPrerequisitesCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/check_cdc_prerequisites/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesConnectionsListSchema = () => z.object({})

const externalDataSourcesConnectionsList = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesConnectionsListSchema>,
    WithPostHogUrl<Schemas.ExternalDataSourceConnectionOption[]>
> => ({
    name: 'external-data-sources-connections-list',
    schema: ExternalDataSourcesConnectionsListSchema(),
    handler: async (
        context: Context,
        _params: z.infer<ReturnType<typeof ExternalDataSourcesConnectionsListSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataSourceConnectionOption[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/connections/`,
        })
        return await withPostHogUrl(context, result, '/data-management/sources')
    },
})

const ExternalDataSourcesCreateSchema = () => {
    const ExternalDataSourcesCreateBody = orvalSchemas.ExternalDataSourcesCreateBody()
    return ExternalDataSourcesCreateBody.extend({
        source_type: ExternalDataSourceTypeSchema,
        payload: ExternalDataSourcePayloadSchema,
    })
}

const externalDataSourcesCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesCreateSchema>,
    Schemas.ExternalDataSourceCreateResponse
> => ({
    name: 'external-data-sources-create',
    schema: ExternalDataSourcesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.access_method !== undefined) {
            body['access_method'] = params.access_method
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.destination_ids !== undefined) {
            body['destination_ids'] = params.destination_ids
        }
        body['created_via'] = 'mcp'
        const result = await context.api.request<Schemas.ExternalDataSourceCreateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesCreateWebhookCreateSchema = () => {
    const ExternalDataSourcesCreateWebhookCreateBody = orvalSchemas.ExternalDataSourcesCreateWebhookCreateBody()
    const ExternalDataSourcesCreateWebhookCreateParams = orvalSchemas.ExternalDataSourcesCreateWebhookCreateParams()
    return ExternalDataSourcesCreateWebhookCreateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesCreateWebhookCreateBody.shape
    )
}

const externalDataSourcesCreateWebhookCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesCreateWebhookCreateSchema>,
    unknown
> => ({
    name: 'external-data-sources-create-webhook-create',
    schema: ExternalDataSourcesCreateWebhookCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesCreateWebhookCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.client_secret !== undefined) {
            body['client_secret'] = params.client_secret
        }
        if (params.account_id !== undefined) {
            body['account_id'] = params.account_id
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        if (params.job_inputs !== undefined) {
            body['job_inputs'] = params.job_inputs
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/create_webhook/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesDeleteWebhookCreateSchema = () => {
    const ExternalDataSourcesDeleteWebhookCreateBody = orvalSchemas.ExternalDataSourcesDeleteWebhookCreateBody()
    const ExternalDataSourcesDeleteWebhookCreateParams = orvalSchemas.ExternalDataSourcesDeleteWebhookCreateParams()
    return ExternalDataSourcesDeleteWebhookCreateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesDeleteWebhookCreateBody.shape
    )
}

const externalDataSourcesDeleteWebhookCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesDeleteWebhookCreateSchema>,
    unknown
> => ({
    name: 'external-data-sources-delete-webhook-create',
    schema: ExternalDataSourcesDeleteWebhookCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesDeleteWebhookCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.client_secret !== undefined) {
            body['client_secret'] = params.client_secret
        }
        if (params.account_id !== undefined) {
            body['account_id'] = params.account_id
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        if (params.job_inputs !== undefined) {
            body['job_inputs'] = params.job_inputs
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/delete_webhook/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesDestinationsRetrieveSchema = () => {
    const ExternalDataSourcesDestinationsRetrieveParams = orvalSchemas.ExternalDataSourcesDestinationsRetrieveParams()
    return ExternalDataSourcesDestinationsRetrieveParams.omit({ project_id: true })
}

const externalDataSourcesDestinationsRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesDestinationsRetrieveSchema>,
    Schemas.SourceDestinations
> => ({
    name: 'external-data-sources-destinations-retrieve',
    schema: ExternalDataSourcesDestinationsRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesDestinationsRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SourceDestinations>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/destinations/`,
        })
        return result
    },
})

const ExternalDataSourcesDestroySchema = () => {
    const ExternalDataSourcesDestroyParams = orvalSchemas.ExternalDataSourcesDestroyParams()
    return ExternalDataSourcesDestroyParams.omit({ project_id: true })
}

const externalDataSourcesDestroy = (): ToolBase<ReturnType<typeof ExternalDataSourcesDestroySchema>, unknown> => ({
    name: 'external-data-sources-destroy',
    schema: ExternalDataSourcesDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExternalDataSourcesListSchema = () => {
    const ExternalDataSourcesListQueryParams = orvalSchemas.ExternalDataSourcesListQueryParams()
    return ExternalDataSourcesListQueryParams
}

const externalDataSourcesList = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesListSchema>,
    WithPostHogUrl<Schemas.PaginatedExternalDataSourceSerializersList>
> => ({
    name: 'external-data-sources-list',
    schema: ExternalDataSourcesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExternalDataSourceSerializersList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/data-management/sources')
    },
})

const ExternalDataSourcesPartialUpdateSchema = () => {
    const ExternalDataSourcesPartialUpdateBody = orvalSchemas.ExternalDataSourcesPartialUpdateBody()
    const ExternalDataSourcesPartialUpdateParams = orvalSchemas.ExternalDataSourcesPartialUpdateParams()
    return ExternalDataSourcesPartialUpdateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesPartialUpdateBody.shape
    )
}

const externalDataSourcesPartialUpdate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesPartialUpdateSchema>,
    Schemas.ExternalDataSourceSerializers
> => ({
    name: 'external-data-sources-partial-update',
    schema: ExternalDataSourcesPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.client_secret !== undefined) {
            body['client_secret'] = params.client_secret
        }
        if (params.account_id !== undefined) {
            body['account_id'] = params.account_id
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        if (params.job_inputs !== undefined) {
            body['job_inputs'] = params.job_inputs
        }
        const result = await context.api.request<Schemas.ExternalDataSourceSerializers>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesRefreshSchemasSchema = () => {
    const ExternalDataSourcesRefreshSchemasCreateBody = orvalSchemas.ExternalDataSourcesRefreshSchemasCreateBody()
    const ExternalDataSourcesRefreshSchemasCreateParams = orvalSchemas.ExternalDataSourcesRefreshSchemasCreateParams()
    return ExternalDataSourcesRefreshSchemasCreateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesRefreshSchemasCreateBody.shape
    )
}

const externalDataSourcesRefreshSchemas = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesRefreshSchemasSchema>,
    unknown
> => ({
    name: 'external-data-sources-refresh-schemas',
    schema: ExternalDataSourcesRefreshSchemasSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesRefreshSchemasSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/refresh_schemas/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesReloadSchema = () => {
    const ExternalDataSourcesReloadCreateBody = orvalSchemas.ExternalDataSourcesReloadCreateBody()
    const ExternalDataSourcesReloadCreateParams = orvalSchemas.ExternalDataSourcesReloadCreateParams()
    return ExternalDataSourcesReloadCreateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesReloadCreateBody.shape
    )
}

const externalDataSourcesReload = (): ToolBase<ReturnType<typeof ExternalDataSourcesReloadSchema>, unknown> => ({
    name: 'external-data-sources-reload',
    schema: ExternalDataSourcesReloadSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesReloadSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/reload/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesRepairCdcCreateSchema = () => {
    const ExternalDataSourcesRepairCdcCreateParams = orvalSchemas.ExternalDataSourcesRepairCdcCreateParams()
    return ExternalDataSourcesRepairCdcCreateParams.omit({ project_id: true })
}

const externalDataSourcesRepairCdcCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesRepairCdcCreateSchema>,
    unknown
> => ({
    name: 'external-data-sources-repair-cdc-create',
    schema: ExternalDataSourcesRepairCdcCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesRepairCdcCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/repair_cdc/`,
        })
        return result
    },
})

const ExternalDataSourcesRetrieveSchema = () => {
    const ExternalDataSourcesRetrieveParams = orvalSchemas.ExternalDataSourcesRetrieveParams()
    return ExternalDataSourcesRetrieveParams.omit({ project_id: true })
}

const externalDataSourcesRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesRetrieveSchema>,
    Schemas.ExternalDataSourceSerializers
> => ({
    name: 'external-data-sources-retrieve',
    schema: ExternalDataSourcesRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataSourceSerializers>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'schemas.*.table.columns',
            'schemas.*.available_columns',
        ]) as typeof result
        return filtered
    },
})

const ExternalDataSourcesUpdateWebhookInputsCreateSchema = () => {
    const ExternalDataSourcesUpdateWebhookInputsCreateBody =
        orvalSchemas.ExternalDataSourcesUpdateWebhookInputsCreateBody()
    const ExternalDataSourcesUpdateWebhookInputsCreateParams =
        orvalSchemas.ExternalDataSourcesUpdateWebhookInputsCreateParams()
    return ExternalDataSourcesUpdateWebhookInputsCreateParams.omit({ project_id: true }).extend(
        ExternalDataSourcesUpdateWebhookInputsCreateBody.shape
    )
}

const externalDataSourcesUpdateWebhookInputsCreate = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesUpdateWebhookInputsCreateSchema>,
    unknown
> => ({
    name: 'external-data-sources-update-webhook-inputs-create',
    schema: ExternalDataSourcesUpdateWebhookInputsCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesUpdateWebhookInputsCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.client_secret !== undefined) {
            body['client_secret'] = params.client_secret
        }
        if (params.account_id !== undefined) {
            body['account_id'] = params.account_id
        }
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        if (params.auto_sync_new_schemas !== undefined) {
            body['auto_sync_new_schemas'] = params.auto_sync_new_schemas
        }
        if (params.auto_sync_schema_patterns !== undefined) {
            body['auto_sync_schema_patterns'] = params.auto_sync_schema_patterns
        }
        if (params.job_inputs !== undefined) {
            body['job_inputs'] = params.job_inputs
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/update_webhook_inputs/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesWebhookInfoRetrieveSchema = () => {
    const ExternalDataSourcesWebhookInfoRetrieveParams = orvalSchemas.ExternalDataSourcesWebhookInfoRetrieveParams()
    return ExternalDataSourcesWebhookInfoRetrieveParams.omit({ project_id: true })
}

const externalDataSourcesWebhookInfoRetrieve = (): ToolBase<
    ReturnType<typeof ExternalDataSourcesWebhookInfoRetrieveSchema>,
    unknown
> => ({
    name: 'external-data-sources-webhook-info-retrieve',
    schema: ExternalDataSourcesWebhookInfoRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ExternalDataSourcesWebhookInfoRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/webhook_info/`,
        })
        return result
    },
})

const ExternalDataSourcesWizardSchema = () => {
    const ExternalDataSourcesWizardRetrieveQueryParams = orvalSchemas.ExternalDataSourcesWizardRetrieveQueryParams()
    return ExternalDataSourcesWizardRetrieveQueryParams.extend({
        fields: z
            .array(z.enum(['*.name', '*.caption', '*.docsUrl', '*.featured', '*.unreleasedSource', '*.fields']))
            .min(1)
            .optional()
            .describe(
                'Optional subset of response fields to return, each a dot-path from the allowlist. Omit to return all fields. Request only the fields your task needs to keep responses small.'
            ),
    })
}

const externalDataSourcesWizard = (): ToolBase<ReturnType<typeof ExternalDataSourcesWizardSchema>, unknown> => ({
    name: 'external-data-sources-wizard',
    schema: ExternalDataSourcesWizardSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ExternalDataSourcesWizardSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/wizard/`,
            query: {
                source_type: params.source_type,
            },
        })
        const filtered = pickResponseFields(
            result,
            params.fields?.length
                ? params.fields
                : ['*.name', '*.caption', '*.docsUrl', '*.featured', '*.unreleasedSource', '*.fields']
        ) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'data-warehouse-source-connect-link': dataWarehouseSourceConnectLink,
    'data-warehouse-source-setup': dataWarehouseSourceSetup,
    'data-warehouse-stored-credentials-list': dataWarehouseStoredCredentialsList,
    'external-data-destinations-list': externalDataDestinationsList,
    'external-data-destinations-retrieve': externalDataDestinationsRetrieve,
    'external-data-schemas-cancel': externalDataSchemasCancel,
    'external-data-schemas-delete-data': externalDataSchemasDeleteData,
    'external-data-schemas-destinations-retrieve': externalDataSchemasDestinationsRetrieve,
    'external-data-schemas-incremental-fields-create': externalDataSchemasIncrementalFieldsCreate,
    'external-data-schemas-list': externalDataSchemasList,
    'external-data-schemas-partial-update': externalDataSchemasPartialUpdate,
    'external-data-schemas-reload': externalDataSchemasReload,
    'external-data-schemas-resync': externalDataSchemasResync,
    'external-data-schemas-retrieve': externalDataSchemasRetrieve,
    'external-data-sources-check-cdc-prerequisites-create': externalDataSourcesCheckCdcPrerequisitesCreate,
    'external-data-sources-connections-list': externalDataSourcesConnectionsList,
    'external-data-sources-create': externalDataSourcesCreate,
    'external-data-sources-create-webhook-create': externalDataSourcesCreateWebhookCreate,
    'external-data-sources-delete-webhook-create': externalDataSourcesDeleteWebhookCreate,
    'external-data-sources-destinations-retrieve': externalDataSourcesDestinationsRetrieve,
    'external-data-sources-destroy': externalDataSourcesDestroy,
    'external-data-sources-list': externalDataSourcesList,
    'external-data-sources-partial-update': externalDataSourcesPartialUpdate,
    'external-data-sources-refresh-schemas': externalDataSourcesRefreshSchemas,
    'external-data-sources-reload': externalDataSourcesReload,
    'external-data-sources-repair-cdc-create': externalDataSourcesRepairCdcCreate,
    'external-data-sources-retrieve': externalDataSourcesRetrieve,
    'external-data-sources-update-webhook-inputs-create': externalDataSourcesUpdateWebhookInputsCreate,
    'external-data-sources-webhook-info-retrieve': externalDataSourcesWebhookInfoRetrieve,
    'external-data-sources-wizard': externalDataSourcesWizard,
}
