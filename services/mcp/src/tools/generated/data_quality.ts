// AUTO-GENERATED from products/data_quality/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    WarehouseSavedQueriesChecksCheckTypesListParams,
    WarehouseSavedQueriesChecksCreateBody,
    WarehouseSavedQueriesChecksCreateParams,
    WarehouseSavedQueriesChecksDestroyParams,
    WarehouseSavedQueriesChecksPartialUpdateBody,
    WarehouseSavedQueriesChecksPartialUpdateParams,
    WarehouseSavedQueriesChecksRunCreateParams,
    WarehouseSavedQueriesChecksRunsListParams,
    WarehouseTablesChecksCreateBody,
    WarehouseTablesChecksCreateParams,
    WarehouseTablesChecksDestroyParams,
    WarehouseTablesChecksPartialUpdateBody,
    WarehouseTablesChecksPartialUpdateParams,
    WarehouseTablesChecksRunCreateParams,
    WarehouseTablesChecksRunsListParams,
} from '@/generated/data_quality/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DataQualityCheckCreateOnTableSchema = WarehouseTablesChecksCreateParams.omit({ project_id: true }).extend(
    WarehouseTablesChecksCreateBody.shape
)

const dataQualityCheckCreateOnTable = (): ToolBase<
    typeof DataQualityCheckCreateOnTableSchema,
    Schemas.DataQualityCheck
> => ({
    name: 'data-quality-check-create-on-table',
    schema: DataQualityCheckCreateOnTableSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckCreateOnTableSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        body['created_source'] = 'ai_generated'
        const result = await context.api.request<Schemas.DataQualityCheck>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.table_id))}/checks/`,
            body,
        })
        return result
    },
})

const DataQualityCheckCreateOnViewSchema = WarehouseSavedQueriesChecksCreateParams.omit({ project_id: true }).extend(
    WarehouseSavedQueriesChecksCreateBody.shape
)

const dataQualityCheckCreateOnView = (): ToolBase<
    typeof DataQualityCheckCreateOnViewSchema,
    Schemas.DataQualityCheck
> => ({
    name: 'data-quality-check-create-on-view',
    schema: DataQualityCheckCreateOnViewSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckCreateOnViewSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        body['created_source'] = 'ai_generated'
        const result = await context.api.request<Schemas.DataQualityCheck>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/`,
            body,
        })
        return result
    },
})

const DataQualityCheckDeleteOnTableSchema = WarehouseTablesChecksDestroyParams.omit({ project_id: true })

const dataQualityCheckDeleteOnTable = (): ToolBase<typeof DataQualityCheckDeleteOnTableSchema, unknown> => ({
    name: 'data-quality-check-delete-on-table',
    schema: DataQualityCheckDeleteOnTableSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckDeleteOnTableSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.table_id))}/checks/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const DataQualityCheckDeleteOnViewSchema = WarehouseSavedQueriesChecksDestroyParams.omit({ project_id: true })

const dataQualityCheckDeleteOnView = (): ToolBase<typeof DataQualityCheckDeleteOnViewSchema, unknown> => ({
    name: 'data-quality-check-delete-on-view',
    schema: DataQualityCheckDeleteOnViewSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckDeleteOnViewSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const DataQualityCheckResultsOnTableSchema = WarehouseTablesChecksRunsListParams.omit({ project_id: true })

const dataQualityCheckResultsOnTable = (): ToolBase<
    typeof DataQualityCheckResultsOnTableSchema,
    Schemas.DataQualityCheckRun[]
> => ({
    name: 'data-quality-check-results-on-table',
    schema: DataQualityCheckResultsOnTableSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckResultsOnTableSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualityCheckRun[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.table_id))}/checks/${encodeURIComponent(String(params.id))}/runs/`,
        })
        return result
    },
})

const DataQualityCheckResultsOnViewSchema = WarehouseSavedQueriesChecksRunsListParams.omit({ project_id: true })

const dataQualityCheckResultsOnView = (): ToolBase<
    typeof DataQualityCheckResultsOnViewSchema,
    Schemas.DataQualityCheckRun[]
> => ({
    name: 'data-quality-check-results-on-view',
    schema: DataQualityCheckResultsOnViewSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckResultsOnViewSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualityCheckRun[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/${encodeURIComponent(String(params.id))}/runs/`,
        })
        return result
    },
})

const DataQualityCheckRunOnTableSchema = WarehouseTablesChecksRunCreateParams.omit({ project_id: true })

const dataQualityCheckRunOnTable = (): ToolBase<
    typeof DataQualityCheckRunOnTableSchema,
    Schemas.DataQualitySuiteRun
> => ({
    name: 'data-quality-check-run-on-table',
    schema: DataQualityCheckRunOnTableSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckRunOnTableSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualitySuiteRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.table_id))}/checks/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

const DataQualityCheckRunOnViewSchema = WarehouseSavedQueriesChecksRunCreateParams.omit({ project_id: true })

const dataQualityCheckRunOnView = (): ToolBase<
    typeof DataQualityCheckRunOnViewSchema,
    Schemas.DataQualitySuiteRun
> => ({
    name: 'data-quality-check-run-on-view',
    schema: DataQualityCheckRunOnViewSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckRunOnViewSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualitySuiteRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

const DataQualityCheckTypesSchema = WarehouseSavedQueriesChecksCheckTypesListParams.omit({ project_id: true })

const dataQualityCheckTypes = (): ToolBase<typeof DataQualityCheckTypesSchema, Schemas.DataQualityCheckType[]> => ({
    name: 'data-quality-check-types',
    schema: DataQualityCheckTypesSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckTypesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualityCheckType[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/check_types/`,
        })
        return result
    },
})

const DataQualityCheckUpdateOnTableSchema = WarehouseTablesChecksPartialUpdateParams.omit({ project_id: true }).extend(
    WarehouseTablesChecksPartialUpdateBody.shape
)

const dataQualityCheckUpdateOnTable = (): ToolBase<
    typeof DataQualityCheckUpdateOnTableSchema,
    Schemas.DataQualityCheck
> => ({
    name: 'data-quality-check-update-on-table',
    schema: DataQualityCheckUpdateOnTableSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckUpdateOnTableSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        const result = await context.api.request<Schemas.DataQualityCheck>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_tables/${encodeURIComponent(String(params.table_id))}/checks/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const DataQualityCheckUpdateOnViewSchema = WarehouseSavedQueriesChecksPartialUpdateParams.omit({
    project_id: true,
}).extend(WarehouseSavedQueriesChecksPartialUpdateBody.shape)

const dataQualityCheckUpdateOnView = (): ToolBase<
    typeof DataQualityCheckUpdateOnViewSchema,
    Schemas.DataQualityCheck
> => ({
    name: 'data-quality-check-update-on-view',
    schema: DataQualityCheckUpdateOnViewSchema,
    handler: async (context: Context, params: z.infer<typeof DataQualityCheckUpdateOnViewSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        const result = await context.api.request<Schemas.DataQualityCheck>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_saved_queries/${encodeURIComponent(String(params.saved_query_id))}/checks/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'data-quality-check-create-on-table': dataQualityCheckCreateOnTable,
    'data-quality-check-create-on-view': dataQualityCheckCreateOnView,
    'data-quality-check-delete-on-table': dataQualityCheckDeleteOnTable,
    'data-quality-check-delete-on-view': dataQualityCheckDeleteOnView,
    'data-quality-check-results-on-table': dataQualityCheckResultsOnTable,
    'data-quality-check-results-on-view': dataQualityCheckResultsOnView,
    'data-quality-check-run-on-table': dataQualityCheckRunOnTable,
    'data-quality-check-run-on-view': dataQualityCheckRunOnView,
    'data-quality-check-types': dataQualityCheckTypes,
    'data-quality-check-update-on-table': dataQualityCheckUpdateOnTable,
    'data-quality-check-update-on-view': dataQualityCheckUpdateOnView,
}
