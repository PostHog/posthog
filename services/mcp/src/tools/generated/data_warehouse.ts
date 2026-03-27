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

const ViewListSchema = WarehouseSavedQueriesListQueryParams

const viewList = (): ToolBase<typeof ViewListSchema, unknown> => ({
    name: 'view-list',
    schema: ViewListSchema,
    handler: async (context: Context, params: z.infer<typeof ViewListSchema>) => {
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

const ViewCreateSchema = WarehouseSavedQueriesCreateBody

const viewCreate = (): ToolBase<
    typeof ViewCreateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
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
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
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

const ViewGetSchema = WarehouseSavedQueriesRetrieveParams.omit({ project_id: true })

const viewGet = (): ToolBase<typeof ViewGetSchema, Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }> => ({
    name: 'view-get',
    schema: ViewGetSchema,
    handler: async (context: Context, params: z.infer<typeof ViewGetSchema>) => {
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

const ViewUpdateSchema = WarehouseSavedQueriesPartialUpdateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesPartialUpdateBody.shape
)

const viewUpdate = (): ToolBase<
    typeof ViewUpdateSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
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

const ViewDeleteSchema = WarehouseSavedQueriesDestroyParams.omit({ project_id: true })

const viewDelete = (): ToolBase<typeof ViewDeleteSchema, unknown> => ({
    name: 'view-delete',
    schema: ViewDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ViewDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/warehouse_saved_queries/${params.id}/`,
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
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
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

const ViewUnmaterializeSchema = WarehouseSavedQueriesRevertMaterializationCreateParams.omit({
    project_id: true,
}).extend(WarehouseSavedQueriesRevertMaterializationCreateBody.shape)

const viewUnmaterialize = (): ToolBase<
    typeof ViewUnmaterializeSchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
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

const ViewRunSchema = WarehouseSavedQueriesRunCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesRunCreateBody.shape
)

const viewRun = (): ToolBase<typeof ViewRunSchema, Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }> => ({
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
        if (params.edited_history_id !== undefined) {
            body['edited_history_id'] = params.edited_history_id
        }
        if (params.soft_update !== undefined) {
            body['soft_update'] = params.soft_update
        }
        if (params.is_test !== undefined) {
            body['is_test'] = params.is_test
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

const ViewRunHistorySchema = WarehouseSavedQueriesRunHistoryRetrieveParams.omit({ project_id: true })

const viewRunHistory = (): ToolBase<
    typeof ViewRunHistorySchema,
    Schemas.DataWarehouseSavedQuery & { _posthogUrl: string }
> => ({
    name: 'view-run-history',
    schema: ViewRunHistorySchema,
    handler: async (context: Context, params: z.infer<typeof ViewRunHistorySchema>) => {
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
