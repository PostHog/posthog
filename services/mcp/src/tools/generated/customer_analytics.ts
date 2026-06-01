// AUTO-GENERATED from products/customer_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    GroupsTypesMetricsCreateBody,
    GroupsTypesMetricsCreateParams,
    GroupsTypesMetricsDestroyParams,
    GroupsTypesMetricsListParams,
    GroupsTypesMetricsListQueryParams,
    GroupsTypesMetricsPartialUpdateBody,
    GroupsTypesMetricsPartialUpdateParams,
    GroupsTypesMetricsRetrieveParams,
} from '@/generated/customer_analytics/api'
import { UsageMetricFiltersSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UsageMetricsCreateSchema = GroupsTypesMetricsCreateParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsCreateBody.shape)
    .extend({
        group_type_index: GroupsTypesMetricsCreateParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
        filters: UsageMetricFiltersSchema,
        math_property: GroupsTypesMetricsCreateBody.shape['math_property'].describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
    })

const usageMetricsCreate = (): ToolBase<typeof UsageMetricsCreateSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-create',
    schema: UsageMetricsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.format !== undefined) {
            body['format'] = params.format
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.display !== undefined) {
            body['display'] = params.display
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.math !== undefined) {
            body['math'] = params.math
        }
        if (params.math_property !== undefined) {
            body['math_property'] = params.math_property
        }
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/`,
            body,
        })
        return result
    },
})

const UsageMetricsDestroySchema = GroupsTypesMetricsDestroyParams.omit({ project_id: true }).extend({
    group_type_index: GroupsTypesMetricsDestroyParams.shape['group_type_index'].describe(
        'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
    ),
})

const usageMetricsDestroy = (): ToolBase<typeof UsageMetricsDestroySchema, unknown> => ({
    name: 'usage-metrics-destroy',
    schema: UsageMetricsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UsageMetricsListSchema = GroupsTypesMetricsListParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsListQueryParams.shape)
    .extend({
        group_type_index: GroupsTypesMetricsListParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
    })

const usageMetricsList = (): ToolBase<
    typeof UsageMetricsListSchema,
    WithPostHogUrl<Schemas.PaginatedGroupUsageMetricList>
> => ({
    name: 'usage-metrics-list',
    schema: UsageMetricsListSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedGroupUsageMetricList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const UsageMetricsPartialUpdateSchema = GroupsTypesMetricsPartialUpdateParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsPartialUpdateBody.shape)
    .extend({
        group_type_index: GroupsTypesMetricsPartialUpdateParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
        filters: UsageMetricFiltersSchema.optional(),
        math_property: GroupsTypesMetricsPartialUpdateBody.shape['math_property'].describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
    })

const usageMetricsPartialUpdate = (): ToolBase<typeof UsageMetricsPartialUpdateSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-partial-update',
    schema: UsageMetricsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.format !== undefined) {
            body['format'] = params.format
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.display !== undefined) {
            body['display'] = params.display
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.math !== undefined) {
            body['math'] = params.math
        }
        if (params.math_property !== undefined) {
            body['math_property'] = params.math_property
        }
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UsageMetricsRetrieveSchema = GroupsTypesMetricsRetrieveParams.omit({ project_id: true }).extend({
    group_type_index: GroupsTypesMetricsRetrieveParams.shape['group_type_index'].describe(
        'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
    ),
})

const usageMetricsRetrieve = (): ToolBase<typeof UsageMetricsRetrieveSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-retrieve',
    schema: UsageMetricsRetrieveSchema,
    mcpVersion: 1,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'usage-metrics-create': usageMetricsCreate,
    'usage-metrics-destroy': usageMetricsDestroy,
    'usage-metrics-list': usageMetricsList,
    'usage-metrics-partial-update': usageMetricsPartialUpdate,
    'usage-metrics-retrieve': usageMetricsRetrieve,
}
