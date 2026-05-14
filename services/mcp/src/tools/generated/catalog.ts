// AUTO-GENERATED from products/catalog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    CatalogColumnsCreateBody,
    CatalogMetricsCreateBody,
    CatalogNodesCreateBody,
    CatalogRelationshipsCreateBody,
} from '@/generated/catalog/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CatalogColumnsCreateSchema = CatalogColumnsCreateBody

const catalogColumnsCreate = (): ToolBase<typeof CatalogColumnsCreateSchema, Schemas.CatalogColumnDTO> => ({
    name: 'catalog-columns-create',
    schema: CatalogColumnsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CatalogColumnsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.node_id !== undefined) {
            body['node_id'] = params.node_id
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.position !== undefined) {
            body['position'] = params.position
        }
        if (params.clickhouse_type !== undefined) {
            body['clickhouse_type'] = params.clickhouse_type
        }
        if (params.hogql_type !== undefined) {
            body['hogql_type'] = params.hogql_type
        }
        if (params.nullable !== undefined) {
            body['nullable'] = params.nullable
        }
        if (params.synthetic_description !== undefined) {
            body['synthetic_description'] = params.synthetic_description
        }
        if (params.semantic_type !== undefined) {
            body['semantic_type'] = params.semantic_type
        }
        if (params.pii_class !== undefined) {
            body['pii_class'] = params.pii_class
        }
        if (params.generator_model !== undefined) {
            body['generator_model'] = params.generator_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        const result = await context.api.request<Schemas.CatalogColumnDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/catalog/columns/`,
            body,
        })
        return result
    },
})

const CatalogNodesCreateSchema = CatalogNodesCreateBody

const catalogNodesCreate = (): ToolBase<typeof CatalogNodesCreateSchema, Schemas.CatalogNodeDTO> => ({
    name: 'catalog-nodes-create',
    schema: CatalogNodesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CatalogNodesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.warehouse_table_id !== undefined) {
            body['warehouse_table_id'] = params.warehouse_table_id
        }
        if (params.saved_query_id !== undefined) {
            body['saved_query_id'] = params.saved_query_id
        }
        if (params.synthetic_description !== undefined) {
            body['synthetic_description'] = params.synthetic_description
        }
        if (params.semantic_role !== undefined) {
            body['semantic_role'] = params.semantic_role
        }
        if (params.business_domain !== undefined) {
            body['business_domain'] = params.business_domain
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.generator_model !== undefined) {
            body['generator_model'] = params.generator_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        const result = await context.api.request<Schemas.CatalogNodeDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/catalog/nodes/`,
            body,
        })
        return result
    },
})

const CatalogRelationshipsCreateSchema = CatalogRelationshipsCreateBody

const catalogRelationshipsCreate = (): ToolBase<
    typeof CatalogRelationshipsCreateSchema,
    Schemas.CatalogRelationshipDTO
> => ({
    name: 'catalog-relationships-create',
    schema: CatalogRelationshipsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CatalogRelationshipsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_node_id !== undefined) {
            body['source_node_id'] = params.source_node_id
        }
        if (params.target_node_id !== undefined) {
            body['target_node_id'] = params.target_node_id
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.source_column_id !== undefined) {
            body['source_column_id'] = params.source_column_id
        }
        if (params.target_column_id !== undefined) {
            body['target_column_id'] = params.target_column_id
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        if (params.discovered_in_run_id !== undefined) {
            body['discovered_in_run_id'] = params.discovered_in_run_id
        }
        if (params.generator_model !== undefined) {
            body['generator_model'] = params.generator_model
        }
        const result = await context.api.request<Schemas.CatalogRelationshipDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/catalog/relationships/`,
            body,
        })
        return result
    },
})

const CatalogMetricsCreateSchema = CatalogMetricsCreateBody

const catalogMetricsCreate = (): ToolBase<typeof CatalogMetricsCreateSchema, Schemas.CatalogMetricDTO> => ({
    name: 'catalog-metrics-create',
    schema: CatalogMetricsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CatalogMetricsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.definition !== undefined) {
            body['definition'] = params.definition
        }
        if (params.generator_model !== undefined) {
            body['generator_model'] = params.generator_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        const result = await context.api.request<Schemas.CatalogMetricDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/catalog/metrics/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'catalog-columns-create': catalogColumnsCreate,
    'catalog-nodes-create': catalogNodesCreate,
    'catalog-relationships-create': catalogRelationshipsCreate,
    'catalog-metrics-create': catalogMetricsCreate,
}
