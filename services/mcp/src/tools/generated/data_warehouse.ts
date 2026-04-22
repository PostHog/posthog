// AUTO-GENERATED from products/data_warehouse/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ExternalDataSchemasCancelCreateBody,
    ExternalDataSchemasCancelCreateParams,
    ExternalDataSchemasDeleteDataDestroyParams,
    ExternalDataSchemasListQueryParams,
    ExternalDataSchemasPartialUpdateBody,
    ExternalDataSchemasPartialUpdateParams,
    ExternalDataSchemasReloadCreateBody,
    ExternalDataSchemasReloadCreateParams,
    ExternalDataSchemasResyncCreateBody,
    ExternalDataSchemasResyncCreateParams,
    ExternalDataSchemasRetrieveParams,
    ExternalDataSourcesCreateBody,
    ExternalDataSourcesDestroyParams,
    ExternalDataSourcesListQueryParams,
    ExternalDataSourcesPartialUpdateBody,
    ExternalDataSourcesPartialUpdateParams,
    ExternalDataSourcesRefreshSchemasCreateBody,
    ExternalDataSourcesRefreshSchemasCreateParams,
    ExternalDataSourcesReloadCreateBody,
    ExternalDataSourcesReloadCreateParams,
    ExternalDataSourcesRetrieveParams,
    WarehouseSavedQueriesCreateBody,
    WarehouseSavedQueriesDestroyParams,
    WarehouseSavedQueriesListQueryParams,
    WarehouseSavedQueriesMaterializeCreateBody,
    WarehouseSavedQueriesMaterializeCreateParams,
    WarehouseSavedQueriesPartialUpdateBody,
    WarehouseSavedQueriesPartialUpdateParams,
    WarehouseSavedQueriesRetrieveParams,
    WarehouseSavedQueriesRevertMaterializationCreateBody,
    WarehouseSavedQueriesRevertMaterializationCreateParams,
    WarehouseSavedQueriesRunCreateBody,
    WarehouseSavedQueriesRunCreateParams,
    WarehouseSavedQueriesRunHistoryRetrieveParams,
} from '@/generated/data_warehouse/api'
import {
    ExternalDataSchemaCdcTableModeSchema,
    ExternalDataSchemaIncrementalFieldSchema,
    ExternalDataSchemaIncrementalFieldTypeSchema,
    ExternalDataSchemaPrimaryKeyColumnsSchema,
    ExternalDataSchemaSyncFrequencySchema,
    ExternalDataSchemaSyncTimeOfDaySchema,
    ExternalDataSchemaSyncTypeSchema,
    ExternalDataSourcePayloadSchema,
    ExternalDataSourceTypeSchema,
} from '@/schema/tool-inputs'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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
        return await withPostHogUrl(context, result, '/sql')
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
        return await withPostHogUrl(context, result, '/sql')
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
        if (params.prefix !== undefined) {
            body['prefix'] = params.prefix
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.payload !== undefined) {
            body['payload'] = params.payload
        }
        const result = await context.api.request<Schemas.ExternalDataSourceSerializers>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/`,
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

const ExternalDataSourcesRefreshSchemasSchema = ExternalDataSourcesRefreshSchemasCreateParams.omit({
    project_id: true,
}).extend(ExternalDataSourcesRefreshSchemasCreateBody.shape)

const externalDataSourcesRefreshSchemas = (): ToolBase<typeof ExternalDataSourcesRefreshSchemasSchema, unknown> => ({
    name: 'external-data-sources-refresh-schemas',
    schema: ExternalDataSourcesRefreshSchemasSchema,
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesRefreshSchemasSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/refresh_schemas/`,
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/reload/`,
        })
        return result
    },
})

const ExternalDataSourcesWizardSchema = z.object({})

const externalDataSourcesWizard = (): ToolBase<typeof ExternalDataSourcesWizardSchema, unknown> => ({
    name: 'external-data-sources-wizard',
    schema: ExternalDataSourcesWizardSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ExternalDataSourcesWizardSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/wizard/`,
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

const ViewListSchema = WarehouseSavedQueriesListQueryParams

const viewList = (): ToolBase<
    typeof ViewListSchema,
    WithPostHogUrl<Schemas.PaginatedDataWarehouseSavedQueryMinimalList>
> => ({
    name: 'view-list',
    schema: ViewListSchema,
    handler: async (context: Context, params: z.infer<typeof ViewListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDataWarehouseSavedQueryMinimalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/`,
            query: {
                page: params.page,
                search: params.search,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/sql/?open_view=${item.id}`))
                ),
            },
            '/sql'
        )
    },
})

const ViewCreateSchema = WarehouseSavedQueriesCreateBody.extend({
    name: WarehouseSavedQueriesCreateBody.shape['name'].describe(
        'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
    ),
    query: WarehouseSavedQueriesCreateBody.shape['query'].describe(
        'HogQL query definition as a JSON object. Must contain a "query" key with the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
    ),
})

const viewCreate = (): ToolBase<typeof ViewCreateSchema, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-create',
    schema: ViewCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ViewCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.folder_id !== undefined) {
            body['folder_id'] = params.folder_id
        }
        if (params.dag_id !== undefined) {
            body['dag_id'] = params.dag_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewGetSchema = WarehouseSavedQueriesRetrieveParams.omit({ project_id: true })

const viewGet = (): ToolBase<typeof ViewGetSchema, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-get',
    schema: ViewGetSchema,
    handler: async (context: Context, params: z.infer<typeof ViewGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewUpdateSchema = WarehouseSavedQueriesPartialUpdateParams.omit({ project_id: true })
    .extend(WarehouseSavedQueriesPartialUpdateBody.shape)
    .extend({
        name: WarehouseSavedQueriesPartialUpdateBody.shape['name'].describe(
            'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
        ),
        query: WarehouseSavedQueriesPartialUpdateBody.shape['query'].describe(
            'HogQL query definition as a JSON object. Must contain a "query" key with the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
        ),
        edited_history_id: WarehouseSavedQueriesPartialUpdateBody.shape['edited_history_id'].describe(
            'Required when updating the query field. Get this from latest_history_id on the retrieve response. Used for optimistic concurrency control.'
        ),
    })

const viewUpdate = (): ToolBase<typeof ViewUpdateSchema, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-update',
    schema: ViewUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ViewUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.folder_id !== undefined) {
            body['folder_id'] = params.folder_id
        }
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.dag_id !== undefined) {
            body['dag_id'] = params.dag_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewDeleteSchema = WarehouseSavedQueriesDestroyParams.omit({ project_id: true })

const viewDelete = (): ToolBase<typeof ViewDeleteSchema, Schemas.DataWarehouseSavedQuery> => ({
    name: 'view-delete',
    schema: ViewDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ViewDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const ViewMaterializeSchema = WarehouseSavedQueriesMaterializeCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesMaterializeCreateBody.shape
)

const viewMaterialize = (): ToolBase<
    typeof ViewMaterializeSchema,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-materialize',
    schema: ViewMaterializeSchema,
    handler: async (context: Context, params: z.infer<typeof ViewMaterializeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.folder_id !== undefined) {
            body['folder_id'] = params.folder_id
        }
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.dag_id !== undefined) {
            body['dag_id'] = params.dag_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/materialize/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewUnmaterializeSchema = WarehouseSavedQueriesRevertMaterializationCreateParams.omit({
    project_id: true,
}).extend(WarehouseSavedQueriesRevertMaterializationCreateBody.shape)

const viewUnmaterialize = (): ToolBase<
    typeof ViewUnmaterializeSchema,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-unmaterialize',
    schema: ViewUnmaterializeSchema,
    handler: async (context: Context, params: z.infer<typeof ViewUnmaterializeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.folder_id !== undefined) {
            body['folder_id'] = params.folder_id
        }
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.dag_id !== undefined) {
            body['dag_id'] = params.dag_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/revert_materialization/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewRunSchema = WarehouseSavedQueriesRunCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesRunCreateBody.shape
)

const viewRun = (): ToolBase<typeof ViewRunSchema, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-run',
    schema: ViewRunSchema,
    handler: async (context: Context, params: z.infer<typeof ViewRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.folder_id !== undefined) {
            body['folder_id'] = params.folder_id
        }
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.dag_id !== undefined) {
            body['dag_id'] = params.dag_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/run/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
    },
})

const ViewRunHistorySchema = WarehouseSavedQueriesRunHistoryRetrieveParams.omit({ project_id: true })

const viewRunHistory = (): ToolBase<typeof ViewRunHistorySchema, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-run-history',
    schema: ViewRunHistorySchema,
    handler: async (context: Context, params: z.infer<typeof ViewRunHistorySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/run_history/`,
        })
        return await withPostHogUrl(context, result, `/sql/?open_view=${result.id}`)
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

const ExternalDataSchemasPartialUpdateSchema = ExternalDataSchemasPartialUpdateParams.omit({ project_id: true })
    .extend(ExternalDataSchemasPartialUpdateBody.shape)
    .extend({
        sync_type: ExternalDataSchemaSyncTypeSchema.optional(),
        sync_frequency: ExternalDataSchemaSyncFrequencySchema.optional(),
        sync_time_of_day: ExternalDataSchemaSyncTimeOfDaySchema.optional(),
        incremental_field: ExternalDataSchemaIncrementalFieldSchema.optional(),
        incremental_field_type: ExternalDataSchemaIncrementalFieldTypeSchema.optional(),
        primary_key_columns: ExternalDataSchemaPrimaryKeyColumnsSchema.optional(),
        cdc_table_mode: ExternalDataSchemaCdcTableModeSchema.optional(),
    })

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
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
        }
        if (params.sync_time_of_day !== undefined) {
            body['sync_time_of_day'] = params.sync_time_of_day
        }
        if (params.incremental_field !== undefined) {
            body['incremental_field'] = params.incremental_field
        }
        if (params.incremental_field_type !== undefined) {
            body['incremental_field_type'] = params.incremental_field_type
        }
        if (params.primary_key_columns !== undefined) {
            body['primary_key_columns'] = params.primary_key_columns
        }
        if (params.cdc_table_mode !== undefined) {
            body['cdc_table_mode'] = params.cdc_table_mode
        }
        const result = await context.api.request<Schemas.ExternalDataSchema>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
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
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_schemas/${encodeURIComponent(String(params.id))}/resync/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'external-data-schemas-list': externalDataSchemasList,
    'external-data-sources-list': externalDataSourcesList,
    'external-data-sources-create': externalDataSourcesCreate,
    'external-data-sources-retrieve': externalDataSourcesRetrieve,
    'external-data-sources-partial-update': externalDataSourcesPartialUpdate,
    'external-data-sources-destroy': externalDataSourcesDestroy,
    'external-data-sources-refresh-schemas': externalDataSourcesRefreshSchemas,
    'external-data-sources-reload': externalDataSourcesReload,
    'external-data-sources-wizard': externalDataSourcesWizard,
    'view-list': viewList,
    'view-create': viewCreate,
    'view-get': viewGet,
    'view-update': viewUpdate,
    'view-delete': viewDelete,
    'view-materialize': viewMaterialize,
    'view-unmaterialize': viewUnmaterialize,
    'view-run': viewRun,
    'view-run-history': viewRunHistory,
    'external-data-schemas-retrieve': externalDataSchemasRetrieve,
    'external-data-schemas-partial-update': externalDataSchemasPartialUpdate,
    'external-data-schemas-cancel': externalDataSchemasCancel,
    'external-data-schemas-delete-data': externalDataSchemasDeleteData,
    'external-data-schemas-reload': externalDataSchemasReload,
    'external-data-schemas-resync': externalDataSchemasResync,
}
