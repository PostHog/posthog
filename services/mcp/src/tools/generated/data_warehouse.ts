// AUTO-GENERATED from products/data_warehouse/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/data_warehouse/api'
import {
    withPostHogUrl,
    pickResponseFields,
    withInformationalResponse,
    type WithPostHogUrl,
    type WithInformationalResponse,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ManagedWarehouseMetricHistoryGetSchema = () => {
    const DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveQueryParams =
        orvalSchemas.DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveQueryParams()
    return DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveQueryParams
}

const managedWarehouseMetricHistoryGet = (): ToolBase<
    ReturnType<typeof ManagedWarehouseMetricHistoryGetSchema>,
    Schemas.ManagedWarehouseMonitoringSeriesResponse
> => ({
    name: 'managed-warehouse-metric-history-get',
    schema: ManagedWarehouseMetricHistoryGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ManagedWarehouseMetricHistoryGetSchema>>) => {
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

const ManagedWarehouseMonitoringGetSchema = () => z.object({})

const managedWarehouseMonitoringGet = (): ToolBase<
    ReturnType<typeof ManagedWarehouseMonitoringGetSchema>,
    Schemas.ManagedWarehouseMonitoringSnapshotResponse
> => ({
    name: 'managed-warehouse-monitoring-get',
    schema: ManagedWarehouseMonitoringGetSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof ManagedWarehouseMonitoringGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ManagedWarehouseMonitoringSnapshotResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_warehouse/managed-warehouse-monitoring/`,
        })
        return result
    },
})

const SavedQueryColumnAnnotationsCreateSchema = () => {
    const SavedQueryColumnAnnotationsCreateBody = orvalSchemas.SavedQueryColumnAnnotationsCreateBody()
    return SavedQueryColumnAnnotationsCreateBody.extend({
        column_name: SavedQueryColumnAnnotationsCreateBody.shape['column_name'].describe(
            'Column to describe. Use an empty string to describe the view itself.'
        ),
    })
}

const savedQueryColumnAnnotationsCreate = (): ToolBase<
    ReturnType<typeof SavedQueryColumnAnnotationsCreateSchema>,
    Schemas.DataWarehouseSavedQueryColumnAnnotation
> => ({
    name: 'saved-query-column-annotations-create',
    schema: SavedQueryColumnAnnotationsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SavedQueryColumnAnnotationsCreateSchema>>) => {
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

const SavedQueryColumnAnnotationsListSchema = () => {
    const SavedQueryColumnAnnotationsListQueryParams = orvalSchemas.SavedQueryColumnAnnotationsListQueryParams()
    return SavedQueryColumnAnnotationsListQueryParams
}

const savedQueryColumnAnnotationsList = (): ToolBase<
    ReturnType<typeof SavedQueryColumnAnnotationsListSchema>,
    WithPostHogUrl<Schemas.PaginatedDataWarehouseSavedQueryColumnAnnotationList>
> => ({
    name: 'saved-query-column-annotations-list',
    schema: SavedQueryColumnAnnotationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SavedQueryColumnAnnotationsListSchema>>) => {
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

const SqlVariablesCreateSchema = () => {
    const InsightVariablesCreateBody = orvalSchemas.InsightVariablesCreateBody()
    return InsightVariablesCreateBody
}

const sqlVariablesCreate = (): ToolBase<ReturnType<typeof SqlVariablesCreateSchema>, Schemas.InsightVariable> => ({
    name: 'sql-variables-create',
    schema: SqlVariablesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SqlVariablesCreateSchema>>) => {
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

const SqlVariablesDeleteSchema = () => {
    const InsightVariablesDestroyParams = orvalSchemas.InsightVariablesDestroyParams()
    return InsightVariablesDestroyParams.omit({ project_id: true })
}

const sqlVariablesDelete = (): ToolBase<ReturnType<typeof SqlVariablesDeleteSchema>, unknown> => ({
    name: 'sql-variables-delete',
    schema: SqlVariablesDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SqlVariablesDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insight_variables/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SqlVariablesUpdateSchema = () => {
    const InsightVariablesPartialUpdateBody = orvalSchemas.InsightVariablesPartialUpdateBody()
    const InsightVariablesPartialUpdateParams = orvalSchemas.InsightVariablesPartialUpdateParams()
    return InsightVariablesPartialUpdateParams.omit({ project_id: true }).extend(
        InsightVariablesPartialUpdateBody.shape
    )
}

const sqlVariablesUpdate = (): ToolBase<ReturnType<typeof SqlVariablesUpdateSchema>, Schemas.InsightVariable> => ({
    name: 'sql-variables-update',
    schema: SqlVariablesUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SqlVariablesUpdateSchema>>) => {
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

const ViewCreateSchema = () => {
    const WarehouseSavedQueriesCreateBody = orvalSchemas.WarehouseSavedQueriesCreateBody()
    return WarehouseSavedQueriesCreateBody.extend({
        name: WarehouseSavedQueriesCreateBody.shape['name'].describe(
            'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
        ),
    })
}

const viewCreate = (): ToolBase<
    ReturnType<typeof ViewCreateSchema>,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-create',
    schema: ViewCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewCreateSchema>>) => {
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

const ViewDeleteSchema = () => {
    const WarehouseSavedQueriesDestroyParams = orvalSchemas.WarehouseSavedQueriesDestroyParams()
    return WarehouseSavedQueriesDestroyParams.omit({ project_id: true })
}

const viewDelete = (): ToolBase<ReturnType<typeof ViewDeleteSchema>, Schemas.DataWarehouseSavedQuery> => ({
    name: 'view-delete',
    schema: ViewDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const ViewGetSchema = () => {
    const WarehouseSavedQueriesRetrieveParams = orvalSchemas.WarehouseSavedQueriesRetrieveParams()
    return WarehouseSavedQueriesRetrieveParams.omit({ project_id: true })
}

const viewGet = (): ToolBase<ReturnType<typeof ViewGetSchema>, WithPostHogUrl<Schemas.DataWarehouseSavedQuery>> => ({
    name: 'view-get',
    schema: ViewGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
    },
})

const ViewListSchema = () => {
    const WarehouseSavedQueriesListQueryParams = orvalSchemas.WarehouseSavedQueriesListQueryParams()
    return WarehouseSavedQueriesListQueryParams
}

const viewList = (): ToolBase<
    ReturnType<typeof ViewListSchema>,
    WithPostHogUrl<Schemas.PaginatedDataWarehouseSavedQueryMinimalList>
> => ({
    name: 'view-list',
    schema: ViewListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewListSchema>>) => {
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

const ViewMaterializeSchema = () => {
    const WarehouseSavedQueriesMaterializeCreateBody = orvalSchemas.WarehouseSavedQueriesMaterializeCreateBody()
    const WarehouseSavedQueriesMaterializeCreateParams = orvalSchemas.WarehouseSavedQueriesMaterializeCreateParams()
    return WarehouseSavedQueriesMaterializeCreateParams.omit({ project_id: true }).extend(
        WarehouseSavedQueriesMaterializeCreateBody.shape
    )
}

const viewMaterialize = (): ToolBase<ReturnType<typeof ViewMaterializeSchema>, unknown> => ({
    name: 'view-materialize',
    schema: ViewMaterializeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewMaterializeSchema>>) => {
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

const ViewRunSchema = () => {
    const WarehouseSavedQueriesRunCreateBody = orvalSchemas.WarehouseSavedQueriesRunCreateBody()
    const WarehouseSavedQueriesRunCreateParams = orvalSchemas.WarehouseSavedQueriesRunCreateParams()
    return WarehouseSavedQueriesRunCreateParams.omit({ project_id: true }).extend(
        WarehouseSavedQueriesRunCreateBody.shape
    )
}

const viewRun = (): ToolBase<ReturnType<typeof ViewRunSchema>, unknown> => ({
    name: 'view-run',
    schema: ViewRunSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewRunSchema>>) => {
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

const ViewRunHistorySchema = () => {
    const WarehouseSavedQueriesRunHistoryRetrieveParams = orvalSchemas.WarehouseSavedQueriesRunHistoryRetrieveParams()
    return WarehouseSavedQueriesRunHistoryRetrieveParams.omit({ project_id: true })
}

const viewRunHistory = (): ToolBase<
    ReturnType<typeof ViewRunHistorySchema>,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-run-history',
    schema: ViewRunHistorySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewRunHistorySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.id))}/run_history/`,
        })
        return await withPostHogUrl(context, result, `/sql?open_view=${result.id}`)
    },
})

const ViewUnmaterializeSchema = () => {
    const WarehouseSavedQueriesRevertMaterializationCreateBody =
        orvalSchemas.WarehouseSavedQueriesRevertMaterializationCreateBody()
    const WarehouseSavedQueriesRevertMaterializationCreateParams =
        orvalSchemas.WarehouseSavedQueriesRevertMaterializationCreateParams()
    return WarehouseSavedQueriesRevertMaterializationCreateParams.omit({ project_id: true }).extend(
        WarehouseSavedQueriesRevertMaterializationCreateBody.shape
    )
}

const viewUnmaterialize = (): ToolBase<
    ReturnType<typeof ViewUnmaterializeSchema>,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-unmaterialize',
    schema: ViewUnmaterializeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewUnmaterializeSchema>>) => {
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

const ViewUpdateSchema = () => {
    const WarehouseSavedQueriesPartialUpdateBody = orvalSchemas.WarehouseSavedQueriesPartialUpdateBody()
    const WarehouseSavedQueriesPartialUpdateParams = orvalSchemas.WarehouseSavedQueriesPartialUpdateParams()
    return WarehouseSavedQueriesPartialUpdateParams.omit({ project_id: true })
        .extend(WarehouseSavedQueriesPartialUpdateBody.shape)
        .extend({
            name: WarehouseSavedQueriesPartialUpdateBody.shape['name'].describe(
                'Unique name for the view. Used as the table name in HogQL queries. Must not conflict with existing table names.'
            ),
            edited_history_id: WarehouseSavedQueriesPartialUpdateBody.shape['edited_history_id'].describe(
                'Required when updating the query field. Get this from latest_history_id on the retrieve response. Used for optimistic concurrency control.'
            ),
        })
}

const viewUpdate = (): ToolBase<
    ReturnType<typeof ViewUpdateSchema>,
    WithPostHogUrl<Schemas.DataWarehouseSavedQuery>
> => ({
    name: 'view-update',
    schema: ViewUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ViewUpdateSchema>>) => {
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

const WarehouseColumnAnnotationsCreateSchema = () => {
    const WarehouseColumnAnnotationsCreateBody = orvalSchemas.WarehouseColumnAnnotationsCreateBody()
    return WarehouseColumnAnnotationsCreateBody.extend({
        column_name: WarehouseColumnAnnotationsCreateBody.shape['column_name'].describe(
            'Column to describe. Use an empty string to describe the table itself.'
        ),
    })
}

const warehouseColumnAnnotationsCreate = (): ToolBase<
    ReturnType<typeof WarehouseColumnAnnotationsCreateSchema>,
    Schemas.WarehouseColumnAnnotation
> => ({
    name: 'warehouse-column-annotations-create',
    schema: WarehouseColumnAnnotationsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseColumnAnnotationsCreateSchema>>) => {
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

const WarehouseColumnAnnotationsListSchema = () => {
    const WarehouseColumnAnnotationsListQueryParams = orvalSchemas.WarehouseColumnAnnotationsListQueryParams()
    return WarehouseColumnAnnotationsListQueryParams
}

const warehouseColumnAnnotationsList = (): ToolBase<
    ReturnType<typeof WarehouseColumnAnnotationsListSchema>,
    WithPostHogUrl<Schemas.PaginatedWarehouseColumnAnnotationList>
> => ({
    name: 'warehouse-column-annotations-list',
    schema: WarehouseColumnAnnotationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseColumnAnnotationsListSchema>>) => {
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

const WarehouseColumnAnnotationsPartialUpdateSchema = () => {
    const WarehouseColumnAnnotationsPartialUpdateBody = orvalSchemas.WarehouseColumnAnnotationsPartialUpdateBody()
    const WarehouseColumnAnnotationsPartialUpdateParams = orvalSchemas.WarehouseColumnAnnotationsPartialUpdateParams()
    return WarehouseColumnAnnotationsPartialUpdateParams.omit({ project_id: true }).extend(
        WarehouseColumnAnnotationsPartialUpdateBody.shape
    )
}

const warehouseColumnAnnotationsPartialUpdate = (): ToolBase<
    ReturnType<typeof WarehouseColumnAnnotationsPartialUpdateSchema>,
    Schemas.WarehouseColumnAnnotation
> => ({
    name: 'warehouse-column-annotations-partial-update',
    schema: WarehouseColumnAnnotationsPartialUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof WarehouseColumnAnnotationsPartialUpdateSchema>>
    ) => {
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

const WarehouseTablesCreateSchema = () => {
    const WarehouseTablesCreateBody = orvalSchemas.WarehouseTablesCreateBody()
    return WarehouseTablesCreateBody.extend({
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
}

const warehouseTablesCreate = (): ToolBase<
    ReturnType<typeof WarehouseTablesCreateSchema>,
    WithInformationalResponse<Schemas.Table>
> => ({
    name: 'warehouse-tables-create',
    schema: WarehouseTablesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseTablesCreateSchema>>) => {
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

const WarehouseTablesRefreshSchemaCreateSchema = () => {
    const WarehouseTablesRefreshSchemaCreateParams = orvalSchemas.WarehouseTablesRefreshSchemaCreateParams()
    return WarehouseTablesRefreshSchemaCreateParams.omit({ project_id: true })
}

const warehouseTablesRefreshSchemaCreate = (): ToolBase<
    ReturnType<typeof WarehouseTablesRefreshSchemaCreateSchema>,
    unknown
> => ({
    name: 'warehouse-tables-refresh-schema-create',
    schema: WarehouseTablesRefreshSchemaCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseTablesRefreshSchemaCreateSchema>>) => {
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
