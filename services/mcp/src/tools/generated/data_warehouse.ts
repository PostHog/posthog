// AUTO-GENERATED from products/data_warehouse/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveQueryParams,
    InsightVariablesCreateBody,
    InsightVariablesDestroyParams,
    InsightVariablesPartialUpdateBody,
    InsightVariablesPartialUpdateParams,
    SavedQueryColumnAnnotationsCreateBody,
    SavedQueryColumnAnnotationsListQueryParams,
    WarehouseColumnAnnotationsCreateBody,
    WarehouseColumnAnnotationsListQueryParams,
    WarehouseColumnAnnotationsPartialUpdateBody,
    WarehouseColumnAnnotationsPartialUpdateParams,
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
    WarehouseTablesCreateBody,
    WarehouseTablesRefreshSchemaCreateParams,
} from '@/generated/data_warehouse/api'
import {
    withPostHogUrl,
    pickResponseFields,
    withInformationalResponse,
    type WithPostHogUrl,
    type WithInformationalResponse,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ManagedWarehouseMetricHistoryGetSchema = DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveQueryParams

const managedWarehouseMetricHistoryGet = (): ToolBase<
    typeof ManagedWarehouseMetricHistoryGetSchema,
    Schemas.ManagedWarehouseMonitoringSeriesResponse
> => ({
    name: 'managed-warehouse-metric-history-get',
    schema: ManagedWarehouseMetricHistoryGetSchema,
    handler: async (context: Context, params: z.infer<typeof ManagedWarehouseMetricHistoryGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ManagedWarehouseMonitoringSeriesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_warehouse/managed-warehouse-monitoring-timeseries/`,
            query: {
                metric: params.metric,
                window: params.window,
            },
        })
        return result
    },
})

const ManagedWarehouseMonitoringGetSchema = z.object({})

const managedWarehouseMonitoringGet = (): ToolBase<
    typeof ManagedWarehouseMonitoringGetSchema,
    Schemas.ManagedWarehouseMonitoringSnapshotResponse
> => ({
    name: 'managed-warehouse-monitoring-get',
    schema: ManagedWarehouseMonitoringGetSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ManagedWarehouseMonitoringGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ManagedWarehouseMonitoringSnapshotResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_warehouse/managed-warehouse-monitoring/`,
        })
        return result
    },
})

const SavedQueryColumnAnnotationsCreateSchema = SavedQueryColumnAnnotationsCreateBody.extend({
    column_name: SavedQueryColumnAnnotationsCreateBody.shape['column_name'].describe(
        'Column to describe. Use an empty string to describe the view itself.'
    ),
})

const savedQueryColumnAnnotationsCreate = (): ToolBase<
    typeof SavedQueryColumnAnnotationsCreateSchema,
    Schemas.DataWarehouseSavedQueryColumnAnnotation
> => ({
    name: 'saved-query-column-annotations-create',
    schema: SavedQueryColumnAnnotationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SavedQueryColumnAnnotationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.saved_query !== undefined) {
            body['saved_query'] = params.saved_query
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQueryColumnAnnotation>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved_query_column_annotations/`,
            body,
        })
        return result
    },
})

const SavedQueryColumnAnnotationsListSchema = SavedQueryColumnAnnotationsListQueryParams

const savedQueryColumnAnnotationsList = (): ToolBase<
    typeof SavedQueryColumnAnnotationsListSchema,
    WithPostHogUrl<Schemas.PaginatedDataWarehouseSavedQueryColumnAnnotationList>
> => ({
    name: 'saved-query-column-annotations-list',
    schema: SavedQueryColumnAnnotationsListSchema,
    handler: async (context: Context, params: z.infer<typeof SavedQueryColumnAnnotationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDataWarehouseSavedQueryColumnAnnotationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved_query_column_annotations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                saved_query_id: params.saved_query_id,
            },
        })
        return await withPostHogUrl(context, result, '/sql')
    },
})

const SqlVariablesCreateSchema = InsightVariablesCreateBody

const sqlVariablesCreate = (): ToolBase<typeof SqlVariablesCreateSchema, Schemas.InsightVariable> => ({
    name: 'sql-variables-create',
    schema: SqlVariablesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SqlVariablesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.default_value !== undefined) {
            body['default_value'] = params.default_value
        }
        if (params.values !== undefined) {
            body['values'] = params.values
        }
        if (params.is_multi !== undefined) {
            body['is_multi'] = params.is_multi
        }
        if (params.values_query !== undefined) {
            body['values_query'] = params.values_query
        }
        if (params.values_query_connection_id !== undefined) {
            body['values_query_connection_id'] = params.values_query_connection_id
        }
        const result = await context.api.request<Schemas.InsightVariable>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insight_variables/`,
            body,
        })
        return result
    },
})

const SqlVariablesDeleteSchema = InsightVariablesDestroyParams.omit({ project_id: true })

const sqlVariablesDelete = (): ToolBase<typeof SqlVariablesDeleteSchema, unknown> => ({
    name: 'sql-variables-delete',
    schema: SqlVariablesDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SqlVariablesDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insight_variables/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SqlVariablesUpdateSchema = InsightVariablesPartialUpdateParams.omit({ project_id: true }).extend(
    InsightVariablesPartialUpdateBody.shape
)

const sqlVariablesUpdate = (): ToolBase<typeof SqlVariablesUpdateSchema, Schemas.InsightVariable> => ({
    name: 'sql-variables-update',
    schema: SqlVariablesUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SqlVariablesUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.default_value !== undefined) {
            body['default_value'] = params.default_value
        }
        if (params.values !== undefined) {
            body['values'] = params.values
        }
        if (params.is_multi !== undefined) {
            body['is_multi'] = params.is_multi
        }
        if (params.values_query !== undefined) {
            body['values_query'] = params.values_query
        }
        if (params.values_query_connection_id !== undefined) {
            body['values_query_connection_id'] = params.values_query_connection_id
        }
        const result = await context.api.request<Schemas.InsightVariable>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insight_variables/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const ViewCreateSchema = WarehouseSavedQueriesCreateBody.extend({
    name: WarehouseSavedQueriesCreateBody.shape['name'].describe(
        'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
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
        if (params.incremental !== undefined) {
            body['incremental'] = params.incremental
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
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
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
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
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
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
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/sql?open_view=${item.id}`))
                ),
            },
            '/sql'
        )
    },
})

const ViewMaterializeSchema = WarehouseSavedQueriesMaterializeCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesMaterializeCreateBody.shape
)

const viewMaterialize = (): ToolBase<typeof ViewMaterializeSchema, unknown> => ({
    name: 'view-materialize',
    schema: ViewMaterializeSchema,
    handler: async (context: Context, params: z.infer<typeof ViewMaterializeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/materialize/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql?open_view=${params.id}`)
    },
})

const ViewRunSchema = WarehouseSavedQueriesRunCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesRunCreateBody.shape
)

const viewRun = (): ToolBase<typeof ViewRunSchema, unknown> => ({
    name: 'view-run',
    schema: ViewRunSchema,
    handler: async (context: Context, params: z.infer<typeof ViewRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.full_refresh !== undefined) {
            body['full_refresh'] = params.full_refresh
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/run/`,
            body,
        })
        return await withPostHogUrl(context, result, `/sql?open_view=${params.id}`)
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
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
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
        if (params.incremental !== undefined) {
            body['incremental'] = params.incremental
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
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
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
    },
})

const ViewUpdateSchema = WarehouseSavedQueriesPartialUpdateParams.omit({ project_id: true })
    .extend(WarehouseSavedQueriesPartialUpdateBody.shape)
    .extend({
        name: WarehouseSavedQueriesPartialUpdateBody.shape['name'].describe(
            'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
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
        if (params.incremental !== undefined) {
            body['incremental'] = params.incremental
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.sync_frequency !== undefined) {
            body['sync_frequency'] = params.sync_frequency
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
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
    },
})

const WarehouseColumnAnnotationsCreateSchema = WarehouseColumnAnnotationsCreateBody.extend({
    column_name: WarehouseColumnAnnotationsCreateBody.shape['column_name'].describe(
        'Column to describe. Use an empty string to describe the table itself.'
    ),
})

const warehouseColumnAnnotationsCreate = (): ToolBase<
    typeof WarehouseColumnAnnotationsCreateSchema,
    Schemas.WarehouseColumnAnnotation
> => ({
    name: 'warehouse-column-annotations-create',
    schema: WarehouseColumnAnnotationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseColumnAnnotationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.table !== undefined) {
            body['table'] = params.table
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.WarehouseColumnAnnotation>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_column_annotations/`,
            body,
        })
        return result
    },
})

const WarehouseColumnAnnotationsListSchema = WarehouseColumnAnnotationsListQueryParams

const warehouseColumnAnnotationsList = (): ToolBase<
    typeof WarehouseColumnAnnotationsListSchema,
    WithPostHogUrl<Schemas.PaginatedWarehouseColumnAnnotationList>
> => ({
    name: 'warehouse-column-annotations-list',
    schema: WarehouseColumnAnnotationsListSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseColumnAnnotationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedWarehouseColumnAnnotationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_column_annotations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                table_id: params.table_id,
            },
        })
        return await withPostHogUrl(context, result, '/sql')
    },
})

const WarehouseColumnAnnotationsPartialUpdateSchema = WarehouseColumnAnnotationsPartialUpdateParams.omit({
    project_id: true,
}).extend(WarehouseColumnAnnotationsPartialUpdateBody.shape)

const warehouseColumnAnnotationsPartialUpdate = (): ToolBase<
    typeof WarehouseColumnAnnotationsPartialUpdateSchema,
    Schemas.WarehouseColumnAnnotation
> => ({
    name: 'warehouse-column-annotations-partial-update',
    schema: WarehouseColumnAnnotationsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseColumnAnnotationsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.table !== undefined) {
            body['table'] = params.table
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.WarehouseColumnAnnotation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_column_annotations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const WarehouseTablesCreateSchema = WarehouseTablesCreateBody.extend({
    name: WarehouseTablesCreateBody.shape['name'].describe(
        "Name the agent and the user will query this table by in HogQL. Pick a short snake_case name that describes the data (e.g. `orders`, `stripe_payouts`). It must be unique across the project's tables and views."
    ),
    format: WarehouseTablesCreateBody.shape['format'].describe(
        'File format of the objects the pattern matches, one of CSV, CSVWithNames (a CSV whose first row is a header), Parquet, JSONEachRow (newline-delimited JSON), or Delta. Do not pass DeltaS3Wrapper, which PostHog uses for its own materialized views.'
    ),
    credential: WarehouseTablesCreateBody.shape['credential'].describe(
        'Send only `access_key` and `access_secret`, the credentials for the bucket in `url_pattern`. The other fields are set by PostHog and are ignored on create.'
    ),
})

const warehouseTablesCreate = (): ToolBase<
    typeof WarehouseTablesCreateSchema,
    WithInformationalResponse<Schemas.Table>
> => ({
    name: 'warehouse-tables-create',
    schema: WarehouseTablesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseTablesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.format !== undefined) {
            body['format'] = params.format
        }
        if (params.url_pattern !== undefined) {
            body['url_pattern'] = params.url_pattern
        }
        if (params.credential !== undefined) {
            body['credential'] = params.credential
        }
        if (params.options !== undefined) {
            body['options'] = params.options
        }
        const result = await context.api.request<Schemas.Table>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'name',
            'hogql_name',
            'format',
            'url_pattern',
            'created_via',
            'columns',
        ]) as typeof result
        return withInformationalResponse(
            filtered,
            'warehouse-table-record',
            "Use the returned columns only to describe the new table's schema to the user."
        )
    },
})

const WarehouseTablesRefreshSchemaCreateSchema = WarehouseTablesRefreshSchemaCreateParams.omit({ project_id: true })

const warehouseTablesRefreshSchemaCreate = (): ToolBase<typeof WarehouseTablesRefreshSchemaCreateSchema, unknown> => ({
    name: 'warehouse-tables-refresh-schema-create',
    schema: WarehouseTablesRefreshSchemaCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseTablesRefreshSchemaCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.id))}/refresh_schema/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'managed-warehouse-metric-history-get': managedWarehouseMetricHistoryGet,
    'managed-warehouse-monitoring-get': managedWarehouseMonitoringGet,
    'saved-query-column-annotations-create': savedQueryColumnAnnotationsCreate,
    'saved-query-column-annotations-list': savedQueryColumnAnnotationsList,
    'sql-variables-create': sqlVariablesCreate,
    'sql-variables-delete': sqlVariablesDelete,
    'sql-variables-update': sqlVariablesUpdate,
    'view-create': viewCreate,
    'view-delete': viewDelete,
    'view-get': viewGet,
    'view-list': viewList,
    'view-materialize': viewMaterialize,
    'view-run': viewRun,
    'view-run-history': viewRunHistory,
    'view-unmaterialize': viewUnmaterialize,
    'view-update': viewUpdate,
    'warehouse-column-annotations-create': warehouseColumnAnnotationsCreate,
    'warehouse-column-annotations-list': warehouseColumnAnnotationsList,
    'warehouse-column-annotations-partial-update': warehouseColumnAnnotationsPartialUpdate,
    'warehouse-tables-create': warehouseTablesCreate,
    'warehouse-tables-refresh-schema-create': warehouseTablesRefreshSchemaCreate,
}
