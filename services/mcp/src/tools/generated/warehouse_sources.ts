// AUTO-GENERATED from products/warehouse_sources/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ExternalDataSchemasCancelCreateBody,
    ExternalDataSchemasCancelCreateParams,
    ExternalDataSchemasDeleteDataDestroyParams,
    ExternalDataSchemasIncrementalFieldsCreateBody,
    ExternalDataSchemasIncrementalFieldsCreateParams,
    ExternalDataSchemasListQueryParams,
    ExternalDataSchemasPartialUpdateBody,
    ExternalDataSchemasPartialUpdateParams,
    ExternalDataSchemasReloadCreateBody,
    ExternalDataSchemasReloadCreateParams,
    ExternalDataSchemasResyncCreateBody,
    ExternalDataSchemasResyncCreateParams,
    ExternalDataSchemasRetrieveParams,
    ExternalDataSourcesConnectLinkRetrieveQueryParams,
    ExternalDataSourcesConnectionsListQueryParams,
    ExternalDataSourcesCreateBody,
    ExternalDataSourcesCreateWebhookCreateBody,
    ExternalDataSourcesCreateWebhookCreateParams,
    ExternalDataSourcesDeleteWebhookCreateBody,
    ExternalDataSourcesDeleteWebhookCreateParams,
    ExternalDataSourcesDestroyParams,
    ExternalDataSourcesListQueryParams,
    ExternalDataSourcesPartialUpdateBody,
    ExternalDataSourcesPartialUpdateParams,
    ExternalDataSourcesRefreshSchemasCreateBody,
    ExternalDataSourcesRefreshSchemasCreateParams,
    ExternalDataSourcesReloadCreateBody,
    ExternalDataSourcesReloadCreateParams,
    ExternalDataSourcesRetrieveParams,
    ExternalDataSourcesSetupCreateBody,
    ExternalDataSourcesStoredCredentialsListQueryParams,
    ExternalDataSourcesUpdateWebhookInputsCreateBody,
    ExternalDataSourcesUpdateWebhookInputsCreateParams,
    ExternalDataSourcesWebhookInfoRetrieveParams,
    ExternalDataSourcesWizardRetrieveQueryParams,
} from '@/generated/warehouse_sources/api'
import { ExternalDataSourcePayloadSchema, ExternalDataSourceTypeSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DataWarehouseSourceConnectLinkSchema = ExternalDataSourcesConnectLinkRetrieveQueryParams.extend({
    source_type: ExternalDataSourceTypeSchema,
})

const dataWarehouseSourceConnectLink = (): ToolBase<
    typeof DataWarehouseSourceConnectLinkSchema,
    Schemas.SourceConnectLink
> => ({
    name: 'data-warehouse-source-connect-link',
    schema: DataWarehouseSourceConnectLinkSchema,
    handler: async (context: Context, params: z.infer<typeof DataWarehouseSourceConnectLinkSchema>) => {
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

const DataWarehouseSourceSetupSchema = ExternalDataSourcesSetupCreateBody.extend({
    source_type: ExternalDataSourceTypeSchema,
})

const dataWarehouseSourceSetup = (): ToolBase<typeof DataWarehouseSourceSetupSchema, Schemas.SourceSetupResponse> => ({
    name: 'data-warehouse-source-setup',
    schema: DataWarehouseSourceSetupSchema,
    handler: async (context: Context, params: z.infer<typeof DataWarehouseSourceSetupSchema>) => {
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

const DataWarehouseStoredCredentialsListSchema = ExternalDataSourcesStoredCredentialsListQueryParams

const dataWarehouseStoredCredentialsList = (): ToolBase<
    typeof DataWarehouseStoredCredentialsListSchema,
    WithPostHogUrl<Schemas.SourceCredential[]>
> => ({
    name: 'data-warehouse-stored-credentials-list',
    schema: DataWarehouseStoredCredentialsListSchema,
    handler: async (context: Context, params: z.infer<typeof DataWarehouseStoredCredentialsListSchema>) => {
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

const ExternalDataSchemasCancelSchema = ExternalDataSchemasCancelCreateParams.omit({ project_id: true }).extend(
    ExternalDataSchemasCancelCreateBody.shape
)

const externalDataSchemasCancel = (): ToolBase<typeof ExternalDataSchemasCancelSchema, unknown> => ({
    name: 'external-data-schemas-cancel',
    schema: ExternalDataSchemasCancelSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasCancelSchema>) => {
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/cancel/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasDeleteDataSchema = ExternalDataSchemasDeleteDataDestroyParams.omit({ project_id: true })

const externalDataSchemasDeleteData = (): ToolBase<typeof ExternalDataSchemasDeleteDataSchema, unknown> => ({
    name: 'external-data-schemas-delete-data',
    schema: ExternalDataSchemasDeleteDataSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasDeleteDataSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/delete_data/`,
        })
        return result
    },
})

const ExternalDataSchemasIncrementalFieldsCreateSchema = ExternalDataSchemasIncrementalFieldsCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSchemasIncrementalFieldsCreateBody.shape)

const externalDataSchemasIncrementalFieldsCreate = (): ToolBase<
    typeof ExternalDataSchemasIncrementalFieldsCreateSchema,
    unknown
> => ({
    name: 'external-data-schemas-incremental-fields-create',
    schema: ExternalDataSchemasIncrementalFieldsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasIncrementalFieldsCreateSchema>) => {
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/incremental_fields/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasListSchema = ExternalDataSchemasListQueryParams

const externalDataSchemasList = (): ToolBase<
    typeof ExternalDataSchemasListSchema,
    WithPostHogUrl<Schemas.PaginatedExternalDataSchemaList>
> => ({
    name: 'external-data-schemas-list',
    schema: ExternalDataSchemasListSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasListSchema>) => {
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

const ExternalDataSchemasPartialUpdateSchema = ExternalDataSchemasPartialUpdateParams.omit({ project_id: true }).extend(
    ExternalDataSchemasPartialUpdateBody.shape
)

const externalDataSchemasPartialUpdate = (): ToolBase<
    typeof ExternalDataSchemasPartialUpdateSchema,
    Schemas.ExternalDataSchema
> => ({
    name: 'external-data-schemas-partial-update',
    schema: ExternalDataSchemasPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasPartialUpdateSchema>) => {
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
        const result = await context.api.request<Schemas.ExternalDataSchema>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasReloadSchema = ExternalDataSchemasReloadCreateParams.omit({ project_id: true }).extend(
    ExternalDataSchemasReloadCreateBody.shape
)

const externalDataSchemasReload = (): ToolBase<typeof ExternalDataSchemasReloadSchema, unknown> => ({
    name: 'external-data-schemas-reload',
    schema: ExternalDataSchemasReloadSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasReloadSchema>) => {
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/reload/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasResyncSchema = ExternalDataSchemasResyncCreateParams.omit({ project_id: true }).extend(
    ExternalDataSchemasResyncCreateBody.shape
)

const externalDataSchemasResync = (): ToolBase<typeof ExternalDataSchemasResyncSchema, unknown> => ({
    name: 'external-data-schemas-resync',
    schema: ExternalDataSchemasResyncSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasResyncSchema>) => {
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/resync/`,
            body,
        })
        return result
    },
})

const ExternalDataSchemasRetrieveSchema = ExternalDataSchemasRetrieveParams.omit({ project_id: true })

const externalDataSchemasRetrieve = (): ToolBase<
    typeof ExternalDataSchemasRetrieveSchema,
    Schemas.ExternalDataSchema
> => ({
    name: 'external-data-schemas-retrieve',
    schema: ExternalDataSchemasRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSchemasRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataSchema>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExternalDataSourcesCheckCdcPrerequisitesCreateSchema = z
    .object({})
    .extend({ source_type: ExternalDataSourceTypeSchema })

const externalDataSourcesCheckCdcPrerequisitesCreate = (): ToolBase<
    typeof ExternalDataSourcesCheckCdcPrerequisitesCreateSchema,
    unknown
> => ({
    name: 'external-data-sources-check-cdc-prerequisites-create',
    schema: ExternalDataSourcesCheckCdcPrerequisitesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesCheckCdcPrerequisitesCreateSchema>) => {
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

const ExternalDataSourcesConnectionsListSchema = ExternalDataSourcesConnectionsListQueryParams

const externalDataSourcesConnectionsList = (): ToolBase<
    typeof ExternalDataSourcesConnectionsListSchema,
    WithPostHogUrl<Schemas.PaginatedExternalDataSourceConnectionOptionList>
> => ({
    name: 'external-data-sources-connections-list',
    schema: ExternalDataSourcesConnectionsListSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesConnectionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedExternalDataSourceConnectionOptionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/connections/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/data-management/sources')
    },
})

const ExternalDataSourcesCreateSchema = ExternalDataSourcesCreateBody.extend({
    source_type: ExternalDataSourceTypeSchema,
    payload: ExternalDataSourcePayloadSchema,
})

const externalDataSourcesCreate = (): ToolBase<
    typeof ExternalDataSourcesCreateSchema,
    Schemas.ExternalDataSourceSerializers
> => ({
    name: 'external-data-sources-create',
    schema: ExternalDataSourcesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesCreateSchema>) => {
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
        body['created_via'] = 'mcp'
        const result = await context.api.request<Schemas.ExternalDataSourceSerializers>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesCreateWebhookCreateSchema = ExternalDataSourcesCreateWebhookCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSourcesCreateWebhookCreateBody.shape)

const externalDataSourcesCreateWebhookCreate = (): ToolBase<
    typeof ExternalDataSourcesCreateWebhookCreateSchema,
    unknown
> => ({
    name: 'external-data-sources-create-webhook-create',
    schema: ExternalDataSourcesCreateWebhookCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesCreateWebhookCreateSchema>) => {
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

const ExternalDataSourcesDeleteWebhookCreateSchema = ExternalDataSourcesDeleteWebhookCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSourcesDeleteWebhookCreateBody.shape)

const externalDataSourcesDeleteWebhookCreate = (): ToolBase<
    typeof ExternalDataSourcesDeleteWebhookCreateSchema,
    unknown
> => ({
    name: 'external-data-sources-delete-webhook-create',
    schema: ExternalDataSourcesDeleteWebhookCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesDeleteWebhookCreateSchema>) => {
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

const ExternalDataSourcesDestroySchema = ExternalDataSourcesDestroyParams.omit({ project_id: true })

const externalDataSourcesDestroy = (): ToolBase<typeof ExternalDataSourcesDestroySchema, unknown> => ({
    name: 'external-data-sources-destroy',
    schema: ExternalDataSourcesDestroySchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExternalDataSourcesListSchema = ExternalDataSourcesListQueryParams

const externalDataSourcesList = (): ToolBase<
    typeof ExternalDataSourcesListSchema,
    WithPostHogUrl<Schemas.PaginatedExternalDataSourceSerializersList>
> => ({
    name: 'external-data-sources-list',
    schema: ExternalDataSourcesListSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesListSchema>) => {
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
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['schemas.*.table.columns', 'schemas.*.available_columns'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/data-management/sources')
    },
})

const ExternalDataSourcesPartialUpdateSchema = ExternalDataSourcesPartialUpdateParams.omit({ project_id: true }).extend(
    ExternalDataSourcesPartialUpdateBody.shape
)

const externalDataSourcesPartialUpdate = (): ToolBase<
    typeof ExternalDataSourcesPartialUpdateSchema,
    Schemas.ExternalDataSourceSerializers
> => ({
    name: 'external-data-sources-partial-update',
    schema: ExternalDataSourcesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesPartialUpdateSchema>) => {
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

const ExternalDataSourcesRefreshSchemasSchema = ExternalDataSourcesRefreshSchemasCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSourcesRefreshSchemasCreateBody.shape)

const externalDataSourcesRefreshSchemas = (): ToolBase<typeof ExternalDataSourcesRefreshSchemasSchema, unknown> => ({
    name: 'external-data-sources-refresh-schemas',
    schema: ExternalDataSourcesRefreshSchemasSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesRefreshSchemasSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/refresh_schemas/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesReloadSchema = ExternalDataSourcesReloadCreateParams.omit({ project_id: true }).extend(
    ExternalDataSourcesReloadCreateBody.shape
)

const externalDataSourcesReload = (): ToolBase<typeof ExternalDataSourcesReloadSchema, unknown> => ({
    name: 'external-data-sources-reload',
    schema: ExternalDataSourcesReloadSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesReloadSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.created_via !== undefined) {
            body['created_via'] = params.created_via
        }
        if (params.direct_query_enabled !== undefined) {
            body['direct_query_enabled'] = params.direct_query_enabled
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/reload/`,
            body,
        })
        return result
    },
})

const ExternalDataSourcesRetrieveSchema = ExternalDataSourcesRetrieveParams.omit({ project_id: true })

const externalDataSourcesRetrieve = (): ToolBase<
    typeof ExternalDataSourcesRetrieveSchema,
    Schemas.ExternalDataSourceSerializers
> => ({
    name: 'external-data-sources-retrieve',
    schema: ExternalDataSourcesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ExternalDataSourceSerializers>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ExternalDataSourcesUpdateWebhookInputsCreateSchema = ExternalDataSourcesUpdateWebhookInputsCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSourcesUpdateWebhookInputsCreateBody.shape)

const externalDataSourcesUpdateWebhookInputsCreate = (): ToolBase<
    typeof ExternalDataSourcesUpdateWebhookInputsCreateSchema,
    unknown
> => ({
    name: 'external-data-sources-update-webhook-inputs-create',
    schema: ExternalDataSourcesUpdateWebhookInputsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesUpdateWebhookInputsCreateSchema>) => {
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

const ExternalDataSourcesWebhookInfoRetrieveSchema = ExternalDataSourcesWebhookInfoRetrieveParams.omit({
    project_id: true,
})

const externalDataSourcesWebhookInfoRetrieve = (): ToolBase<
    typeof ExternalDataSourcesWebhookInfoRetrieveSchema,
    unknown
> => ({
    name: 'external-data-sources-webhook-info-retrieve',
    schema: ExternalDataSourcesWebhookInfoRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesWebhookInfoRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/webhook_info/`,
        })
        return result
    },
})

const ExternalDataSourcesWizardSchema = ExternalDataSourcesWizardRetrieveQueryParams

const externalDataSourcesWizard = (): ToolBase<typeof ExternalDataSourcesWizardSchema, unknown> => ({
    name: 'external-data-sources-wizard',
    schema: ExternalDataSourcesWizardSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesWizardSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/wizard/`,
            query: {
                source_type: params.source_type,
            },
        })
        const filtered = pickResponseFields(result, [
            '*.name',
            '*.caption',
            '*.docsUrl',
            '*.featured',
            '*.unreleasedSource',
            '*.fields',
        ]) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'data-warehouse-source-connect-link': dataWarehouseSourceConnectLink,
    'data-warehouse-source-setup': dataWarehouseSourceSetup,
    'data-warehouse-stored-credentials-list': dataWarehouseStoredCredentialsList,
    'external-data-schemas-cancel': externalDataSchemasCancel,
    'external-data-schemas-delete-data': externalDataSchemasDeleteData,
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
    'external-data-sources-destroy': externalDataSourcesDestroy,
    'external-data-sources-list': externalDataSourcesList,
    'external-data-sources-partial-update': externalDataSourcesPartialUpdate,
    'external-data-sources-refresh-schemas': externalDataSourcesRefreshSchemas,
    'external-data-sources-reload': externalDataSourcesReload,
    'external-data-sources-retrieve': externalDataSourcesRetrieve,
    'external-data-sources-update-webhook-inputs-create': externalDataSourcesUpdateWebhookInputsCreate,
    'external-data-sources-webhook-info-retrieve': externalDataSourcesWebhookInfoRetrieve,
    'external-data-sources-wizard': externalDataSourcesWizard,
}
