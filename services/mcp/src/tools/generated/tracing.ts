// AUTO-GENERATED from products/tracing/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    TracingSpansAggregateCreateBody,
    TracingSpansAttributeBreakdownCreateBody,
    TracingSpansAttributesRetrieveQueryParams,
    TracingSpansCountCreateBody,
    TracingSpansDurationHistogramCreateBody,
    TracingSpansQueryCreateBody,
    TracingSpansServiceNamesRetrieveQueryParams,
    TracingSpansSparklineCreateBody,
    TracingSpansTraceCreateBody,
    TracingSpansTraceCreateParams,
    TracingSpansTreeCreateBody,
    TracingSpansValuesRetrieveQueryParams,
} from '@/generated/tracing/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ApmAttributeBreakdownSchema = TracingSpansAttributeBreakdownCreateBody

const apmAttributeBreakdown = (): ToolBase<
    typeof ApmAttributeBreakdownSchema,
    Schemas._TracingAttributeBreakdownResponse
> => ({
    name: 'apm-attribute-breakdown',
    schema: ApmAttributeBreakdownSchema,
    handler: async (context: Context, params: z.infer<typeof ApmAttributeBreakdownSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._TracingAttributeBreakdownResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/attribute-breakdown/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results', 'compare']) as typeof result
        return filtered
    },
})

const ApmAttributeValuesListSchema = TracingSpansValuesRetrieveQueryParams

const apmAttributeValuesList = (): ToolBase<typeof ApmAttributeValuesListSchema, unknown> => ({
    name: 'apm-attribute-values-list',
    schema: ApmAttributeValuesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApmAttributeValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/values/`,
            query: {
                attribute_type: params.attribute_type,
                key: params.key,
                limit: params.limit,
                offset: params.offset,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmAttributesListSchema = TracingSpansAttributesRetrieveQueryParams

const apmAttributesList = (): ToolBase<typeof ApmAttributesListSchema, Schemas._TracingAttributesResponse> => ({
    name: 'apm-attributes-list',
    schema: ApmAttributesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApmAttributesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._TracingAttributesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/attributes/`,
            query: {
                attribute_type: params.attribute_type,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                search_values: params.search_values,
            },
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
        return filtered
    },
})

const ApmServicesListSchema = TracingSpansServiceNamesRetrieveQueryParams

const apmServicesList = (): ToolBase<typeof ApmServicesListSchema, unknown> => ({
    name: 'apm-services-list',
    schema: ApmServicesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApmServicesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/service-names/`,
            query: {
                dateRange: params.dateRange,
                search: params.search,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmSpansAggregateSchema = TracingSpansAggregateCreateBody

const apmSpansAggregate = (): ToolBase<typeof ApmSpansAggregateSchema, unknown> => ({
    name: 'apm-spans-aggregate',
    schema: ApmSpansAggregateSchema,
    handler: async (context: Context, params: z.infer<typeof ApmSpansAggregateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/aggregate/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results', 'compare']) as typeof result
        return filtered
    },
})

const ApmSpansCountSchema = TracingSpansCountCreateBody

const apmSpansCount = (): ToolBase<typeof ApmSpansCountSchema, Schemas._TracingCountResponse> => ({
    name: 'apm-spans-count',
    schema: ApmSpansCountSchema,
    handler: async (context: Context, params: z.infer<typeof ApmSpansCountSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._TracingCountResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/count/`,
            body,
        })
        const filtered = pickResponseFields(result, ['count']) as typeof result
        return filtered
    },
})

const ApmSpansDurationHistogramSchema = TracingSpansDurationHistogramCreateBody

const apmSpansDurationHistogram = (): ToolBase<typeof ApmSpansDurationHistogramSchema, unknown> => ({
    name: 'apm-spans-duration-histogram',
    schema: ApmSpansDurationHistogramSchema,
    handler: async (context: Context, params: z.infer<typeof ApmSpansDurationHistogramSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/duration-histogram/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmSpansSparklineSchema = TracingSpansSparklineCreateBody

const apmSpansSparkline = (): ToolBase<typeof ApmSpansSparklineSchema, unknown> => ({
    name: 'apm-spans-sparkline',
    schema: ApmSpansSparklineSchema,
    handler: async (context: Context, params: z.infer<typeof ApmSpansSparklineSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/sparkline/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmSpansTreeSchema = TracingSpansTreeCreateBody

const apmSpansTree = (): ToolBase<typeof ApmSpansTreeSchema, unknown> => ({
    name: 'apm-spans-tree',
    schema: ApmSpansTreeSchema,
    handler: async (context: Context, params: z.infer<typeof ApmSpansTreeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/tree/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results', 'compare']) as typeof result
        return filtered
    },
})

const ApmTraceGetSchema = TracingSpansTraceCreateParams.omit({ project_id: true }).extend(
    TracingSpansTraceCreateBody.shape
)

const apmTraceGet = (): ToolBase<typeof ApmTraceGetSchema, unknown> =>
    withUiApp('trace-span-list', {
        name: 'apm-trace-get',
        schema: ApmTraceGetSchema,
        handler: async (context: Context, params: z.infer<typeof ApmTraceGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.dateRange !== undefined) {
                body['dateRange'] = params.dateRange
            }
            if (params.excludeAttributes !== undefined) {
                body['excludeAttributes'] = params.excludeAttributes
            }
            if (params.offset !== undefined) {
                body['offset'] = params.offset
            }
            const result = await context.api.request<unknown>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/trace/${encodeURIComponent(String(params.trace_id))}/`,
                body,
            })
            const filtered = pickResponseFields(result, ['results']) as typeof result
            return await withPostHogUrl(context, filtered, `/tracing/?trace=${params.trace_id}`)
        },
    })

const QueryApmSpansSchema = TracingSpansQueryCreateBody

const queryApmSpans = (): ToolBase<typeof QueryApmSpansSchema, unknown> =>
    withUiApp('trace-span-list', {
        name: 'query-apm-spans',
        schema: QueryApmSpansSchema,
        handler: async (context: Context, params: z.infer<typeof QueryApmSpansSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.query !== undefined) {
                body['query'] = params.query
            }
            const result = await context.api.request<unknown>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/query/`,
                body,
            })
            const filtered = pickResponseFields(result, ['results']) as typeof result
            return filtered
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'apm-attribute-breakdown': apmAttributeBreakdown,
    'apm-attribute-values-list': apmAttributeValuesList,
    'apm-attributes-list': apmAttributesList,
    'apm-services-list': apmServicesList,
    'apm-spans-aggregate': apmSpansAggregate,
    'apm-spans-count': apmSpansCount,
    'apm-spans-duration-histogram': apmSpansDurationHistogram,
    'apm-spans-sparkline': apmSpansSparkline,
    'apm-spans-tree': apmSpansTree,
    'apm-trace-get': apmTraceGet,
    'query-apm-spans': queryApmSpans,
}
