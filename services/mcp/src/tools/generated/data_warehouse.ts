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
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WarehouseSavedQueriesListSchema = WarehouseSavedQueriesListQueryParams

const warehouseSavedQueriesList = (): ToolBase<typeof WarehouseSavedQueriesListSchema, unknown> => ({
    name: 'warehouse-saved-queries-list',
    schema: WarehouseSavedQueriesListSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDataWarehouseSavedQueryMinimalList>({
            method: 'GET',
            path: `/api/projects/${projectId}/warehouse_saved_queries/`,
            query: {
                page: params.page,
                search: params.search,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${item.id}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql`,
        }
    },
})

const WarehouseSavedQueriesCreateSchema = WarehouseSavedQueriesCreateBody

const warehouseSavedQueriesCreate = (): ToolBase<
    typeof WarehouseSavedQueriesCreateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-create',
    schema: WarehouseSavedQueriesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${projectId}/warehouse_saved_queries/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesRetrieveSchema = WarehouseSavedQueriesRetrieveParams.omit({ project_id: true })

const warehouseSavedQueriesRetrieve = (): ToolBase<
    typeof WarehouseSavedQueriesRetrieveSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-retrieve',
    schema: WarehouseSavedQueriesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesPartialUpdateSchema = WarehouseSavedQueriesPartialUpdateParams.omit({
    project_id: true,
}).extend(WarehouseSavedQueriesPartialUpdateBody.shape)

const warehouseSavedQueriesPartialUpdate = (): ToolBase<
    typeof WarehouseSavedQueriesPartialUpdateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-partial-update',
    schema: WarehouseSavedQueriesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesDestroySchema = WarehouseSavedQueriesDestroyParams.omit({ project_id: true })

const warehouseSavedQueriesDestroy = (): ToolBase<typeof WarehouseSavedQueriesDestroySchema, unknown> => ({
    name: 'warehouse-saved-queries-destroy',
    schema: WarehouseSavedQueriesDestroySchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/`,
            body: { deleted: true },
        })
        return result
    },
})

const WarehouseSavedQueriesMaterializeCreateSchema = WarehouseSavedQueriesMaterializeCreateParams.omit({
    project_id: true,
}).extend(WarehouseSavedQueriesMaterializeCreateBody.shape)

const warehouseSavedQueriesMaterializeCreate = (): ToolBase<
    typeof WarehouseSavedQueriesMaterializeCreateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-materialize-create',
    schema: WarehouseSavedQueriesMaterializeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesMaterializeCreateSchema>) => {
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/materialize/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesRevertMaterializationCreateSchema =
    WarehouseSavedQueriesRevertMaterializationCreateParams.omit({ project_id: true }).extend(
        WarehouseSavedQueriesRevertMaterializationCreateBody.shape
    )

const warehouseSavedQueriesRevertMaterializationCreate = (): ToolBase<
    typeof WarehouseSavedQueriesRevertMaterializationCreateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-revert-materialization-create',
    schema: WarehouseSavedQueriesRevertMaterializationCreateSchema,
    handler: async (
        context: Context,
        params: z.infer<typeof WarehouseSavedQueriesRevertMaterializationCreateSchema>
    ) => {
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/revert_materialization/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesRunCreateSchema = WarehouseSavedQueriesRunCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesRunCreateBody.shape
)

const warehouseSavedQueriesRunCreate = (): ToolBase<
    typeof WarehouseSavedQueriesRunCreateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-run-create',
    schema: WarehouseSavedQueriesRunCreateSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesRunCreateSchema>) => {
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'POST',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/run/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

const WarehouseSavedQueriesRunHistoryRetrieveSchema = WarehouseSavedQueriesRunHistoryRetrieveParams.omit({
    project_id: true,
})

const warehouseSavedQueriesRunHistoryRetrieve = (): ToolBase<
    typeof WarehouseSavedQueriesRunHistoryRetrieveSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'warehouse-saved-queries-run-history-retrieve',
    schema: WarehouseSavedQueriesRunHistoryRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof WarehouseSavedQueriesRunHistoryRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataWarehouseSavedQuery>({
            method: 'GET',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/run_history/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/sql/?open_view=${(result as any).id}`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'warehouse-saved-queries-list': warehouseSavedQueriesList,
    'warehouse-saved-queries-create': warehouseSavedQueriesCreate,
    'warehouse-saved-queries-retrieve': warehouseSavedQueriesRetrieve,
    'warehouse-saved-queries-partial-update': warehouseSavedQueriesPartialUpdate,
    'warehouse-saved-queries-destroy': warehouseSavedQueriesDestroy,
    'warehouse-saved-queries-materialize-create': warehouseSavedQueriesMaterializeCreate,
    'warehouse-saved-queries-revert-materialization-create': warehouseSavedQueriesRevertMaterializationCreate,
    'warehouse-saved-queries-run-create': warehouseSavedQueriesRunCreate,
    'warehouse-saved-queries-run-history-retrieve': warehouseSavedQueriesRunHistoryRetrieve,
}
