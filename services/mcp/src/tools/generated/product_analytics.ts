// AUTO-GENERATED from products/product_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    InsightsCreateBody,
    InsightsDestroyParams,
    InsightsListQueryParams,
    InsightsPartialUpdateBody,
    InsightsPartialUpdateParams,
    InsightsRetrieveParams,
    InsightsRetrieveQueryParams,
} from '@/generated/product_analytics/api'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AssistantInsightVizNode = z.object({
    kind: z.literal('InsightVizNode').default('InsightVizNode'),
    source: z
        .record(z.string(), z.unknown())
        .describe(
            'Product analtycs query objects like TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery'
        ),
})

const AssistantDataVisualizationGoalLine = z.object({
    label: z.string().describe('Label rendered next to the goal line.'),
    value: z.coerce.number().describe('Y-axis value at which the goal line is drawn.'),
})

const AssistantDataVisualizationAxis = z.object({
    column: z.string().describe('Name of a column returned by the SQL query to map onto this axis.'),
})

const AssistantDataVisualizationChartSettings = z.object({
    goalLines: z
        .array(AssistantDataVisualizationGoalLine)
        .describe('Horizontal goal lines drawn across the chart.')
        .optional(),
    seriesBreakdownColumn: z
        .string()
        .nullable()
        .describe(
            'Column that splits a single Y series into multiple colored series — e.g. breaking down a line chart by `country`. Set to `null` or omit to disable.'
        )
        .optional(),
    showLegend: z.coerce.boolean().describe('Show the chart legend.').optional(),
    showNullsAsZero: z.coerce.boolean().describe('Replace null aggregation results with zero.').optional(),
    stackBars100: z.coerce
        .boolean()
        .describe('Stack bars to 100% of the total. Only meaningful with `ActionsStackedBar`.')
        .optional(),
    xAxis: AssistantDataVisualizationAxis.describe(
        'Column used as the X axis. Typically a time bucket or categorical column.'
    ).optional(),
    yAxis: z
        .array(AssistantDataVisualizationAxis)
        .describe('One or more numeric columns plotted as Y series.')
        .optional(),
})

const AssistantDataVisualizationDisplayType = z.enum([
    'ActionsTable',
    'BoldNumber',
    'ActionsLineGraph',
    'ActionsBar',
    'ActionsStackedBar',
    'ActionsAreaGraph',
    'TwoDimensionalHeatmap',
])

const AssistantDataVisualizationTableSettings = z.object({
    columns: z
        .array(AssistantDataVisualizationAxis)
        .describe('Columns to display and their order. Omit to show every column returned by the query.')
        .optional(),
    pinnedColumns: z.array(z.string()).describe('Column names to pin to the left of the table.').optional(),
    showTotalRow: z.coerce.boolean().describe('Show a total row at the bottom of the table.').optional(),
    transpose: z.coerce.boolean().describe('Transpose rows and columns.').optional(),
})

const AssistantDataVisualizationNode = z.object({
    chartSettings: AssistantDataVisualizationChartSettings.describe(
        'Chart configuration. Ignored when `display` is `ActionsTable` or `BoldNumber`.'
    ).optional(),
    display: AssistantDataVisualizationDisplayType.describe(
        'Visualization type. Defaults to `ActionsTable` when omitted.\n\nGuidance:\n- Single-value result (one numeric column, one row) → `BoldNumber`.\n- Time series → `ActionsLineGraph` or `ActionsAreaGraph`.\n- Categorical comparison → `ActionsBar` or `ActionsStackedBar`.\n- Two-dimensional aggregation → `TwoDimensionalHeatmap`.\n- Otherwise → `ActionsTable`.'
    ).optional(),
    kind: z.literal('DataVisualizationNode').default('DataVisualizationNode'),
    source: z.record(z.string(), z.unknown()).describe('HogQL query object that produces the rows to visualize.'),
    tableSettings: AssistantDataVisualizationTableSettings.describe(
        'Table configuration. Only applies when `display` is `ActionsTable` or omitted.'
    ).optional(),
})

const InsightQuery = z.union([AssistantInsightVizNode, AssistantDataVisualizationNode])

const InsightCreateSchema = InsightsCreateBody.omit({
    derived_name: true,
    order: true,
    deleted: true,
    _create_in_folder: true,
}).extend({
    query: InsightQuery,
    dashboards: InsightsCreateBody.shape['dashboards'].describe(
        'Dashboard IDs this insight should belong to. This is a full replacement — always include all existing dashboard IDs when adding a new one.'
    ),
})

const insightCreate = (): ToolBase<typeof InsightCreateSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-create',
    schema: InsightCreateSchema,
    handler: async (context: Context, params: z.infer<typeof InsightCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.dashboards !== undefined) {
            body['dashboards'] = params.dashboards
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.favorited !== undefined) {
            body['favorited'] = params.favorited
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.Insight>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightDeleteSchema = InsightsDestroyParams.omit({ project_id: true })

const insightDelete = (): ToolBase<typeof InsightDeleteSchema, Schemas.Insight> => ({
    name: 'insight-delete',
    schema: InsightDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof InsightDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Insight>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const InsightGetSchema = InsightsRetrieveParams.omit({ project_id: true })
    .extend(InsightsRetrieveQueryParams.omit({ format: true, from_dashboard: true, refresh: true }).shape)
    .extend({
        filters_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                "Object (or pre-encoded JSON string) to override the insight's filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token."
            ),
        variables_override: z
            .union([z.string(), z.record(z.string(), z.unknown())])
            .optional()
            .describe(
                'Object (or pre-encoded JSON string) to override the insight\'s HogQL variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `insight-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
            ),
    })

const insightGet = (): ToolBase<typeof InsightGetSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-get',
    schema: InsightGetSchema,
    handler: async (context: Context, params: z.infer<typeof InsightGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Insight>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            query: {
                filters_override: params.filters_override,
                variables_override: params.variables_override,
            },
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightUpdateSchema = InsightsPartialUpdateParams.omit({ project_id: true })
    .extend(
        InsightsPartialUpdateBody.omit({ derived_name: true, order: true, deleted: true, _create_in_folder: true })
            .shape
    )
    .extend({
        query: InsightQuery.optional(),
        dashboards: InsightsPartialUpdateBody.shape['dashboards'].describe(
            'Dashboard IDs this insight should belong to. This is a full replacement — always include all existing dashboard IDs when adding a new one.'
        ),
    })

const insightUpdate = (): ToolBase<typeof InsightUpdateSchema, WithPostHogUrl<Schemas.Insight>> => ({
    name: 'insight-update',
    schema: InsightUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InsightUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.dashboards !== undefined) {
            body['dashboards'] = params.dashboards
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.favorited !== undefined) {
            body['favorited'] = params.favorited
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.Insight>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, [
            'result',
            'hasMore',
            'columns',
            'is_cached',
            'query_status',
            'hogql',
            'types',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/insights/${filtered.short_id}`)
    },
})

const InsightsListSchema = InsightsListQueryParams.omit({ format: true, basic: true, refresh: true })

const insightsList = (): ToolBase<typeof InsightsListSchema, WithPostHogUrl<Schemas.PaginatedInsightList>> => ({
    name: 'insights-list',
    schema: InsightsListSchema,
    handler: async (context: Context, params: z.infer<typeof InsightsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedInsightList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/insights/`,
            query: {
                created_by: params.created_by,
                created_date_from: params.created_date_from,
                created_date_to: params.created_date_to,
                dashboards: params.dashboards,
                date_from: params.date_from,
                date_to: params.date_to,
                favorited: params.favorited,
                insight: params.insight,
                last_viewed_date_from: params.last_viewed_date_from,
                last_viewed_date_to: params.last_viewed_date_to,
                limit: params.limit,
                offset: params.offset,
                saved: params.saved,
                search: params.search,
                short_id: params.short_id,
                tags: params.tags,
                user: params.user,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'short_id',
                    'name',
                    'derived_name',
                    'description',
                    'tags',
                    'favorited',
                    'dashboards',
                    'created_at',
                    'created_by',
                    'last_modified_at',
                    'last_modified_by',
                    'last_viewed_at',
                    'alerts',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/insights/${item.short_id}`))
                ),
            },
            '/insights'
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'insight-create': insightCreate,
    'insight-delete': insightDelete,
    'insight-get': insightGet,
    'insight-update': insightUpdate,
    'insights-list': insightsList,
}
