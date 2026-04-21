// AUTO-GENERATED from products/data_warehouse/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
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
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'view-list': viewList,
    'view-create': viewCreate,
    'view-get': viewGet,
    'view-update': viewUpdate,
    'view-delete': viewDelete,
    'view-materialize': viewMaterialize,
    'view-unmaterialize': viewUnmaterialize,
    'view-run': viewRun,
    'view-run-history': viewRunHistory,
}
