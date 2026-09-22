// AUTO-GENERATED from products/tracing/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/tracing/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ApmAttributeBreakdownSchema = () => {
    const TracingSpansAttributeBreakdownCreateBody = orvalSchemas.TracingSpansAttributeBreakdownCreateBody()
    return TracingSpansAttributeBreakdownCreateBody
}

const apmAttributeBreakdown = (): ToolBase<
    ReturnType<typeof ApmAttributeBreakdownSchema>,
    Schemas._TracingAttributeBreakdownResponse
> => ({
    name: 'apm-attribute-breakdown',
    schema: ApmAttributeBreakdownSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmAttributeBreakdownSchema>>) => {
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

const ApmAttributeValuesListSchema = () => {
    const TracingSpansValuesRetrieveQueryParams = orvalSchemas.TracingSpansValuesRetrieveQueryParams()
    return TracingSpansValuesRetrieveQueryParams
}

const apmAttributeValuesList = (): ToolBase<ReturnType<typeof ApmAttributeValuesListSchema>, unknown> => ({
    name: 'apm-attribute-values-list',
    schema: ApmAttributeValuesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmAttributeValuesListSchema>>) => {
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

const ApmAttributesListSchema = () => {
    const TracingSpansAttributesRetrieveQueryParams = orvalSchemas.TracingSpansAttributesRetrieveQueryParams()
    return TracingSpansAttributesRetrieveQueryParams
}

const apmAttributesList = (): ToolBase<
    ReturnType<typeof ApmAttributesListSchema>,
    Schemas._TracingAttributesResponse
> => ({
    name: 'apm-attributes-list',
    schema: ApmAttributesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmAttributesListSchema>>) => {
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

const ApmServicesListSchema = () => {
    const TracingSpansServiceNamesRetrieveQueryParams = orvalSchemas.TracingSpansServiceNamesRetrieveQueryParams()
    return TracingSpansServiceNamesRetrieveQueryParams
}

const apmServicesList = (): ToolBase<ReturnType<typeof ApmServicesListSchema>, unknown> => ({
    name: 'apm-services-list',
    schema: ApmServicesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmServicesListSchema>>) => {
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

const ApmSpansAggregateSchema = () => {
    const TracingSpansAggregateCreateBody = orvalSchemas.TracingSpansAggregateCreateBody()
    return TracingSpansAggregateCreateBody
}

const apmSpansAggregate = (): ToolBase<
    ReturnType<typeof ApmSpansAggregateSchema>,
    Schemas._TracingAggregationResponse
> => ({
    name: 'apm-spans-aggregate',
    schema: ApmSpansAggregateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansAggregateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._TracingAggregationResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/aggregate/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results', 'compare', 'has_more', 'next_offset']) as typeof result
        return filtered
    },
})

const ApmSpansCountSchema = () => {
    const TracingSpansCountCreateBody = orvalSchemas.TracingSpansCountCreateBody()
    return TracingSpansCountCreateBody
}

const apmSpansCount = (): ToolBase<ReturnType<typeof ApmSpansCountSchema>, Schemas._TracingCountResponse> => ({
    name: 'apm-spans-count',
    schema: ApmSpansCountSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansCountSchema>>) => {
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

const ApmSpansDurationHistogramSchema = () => {
    const TracingSpansDurationHistogramCreateBody = orvalSchemas.TracingSpansDurationHistogramCreateBody()
    return TracingSpansDurationHistogramCreateBody
}

const apmSpansDurationHistogram = (): ToolBase<ReturnType<typeof ApmSpansDurationHistogramSchema>, unknown> => ({
    name: 'apm-spans-duration-histogram',
    schema: ApmSpansDurationHistogramSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansDurationHistogramSchema>>) => {
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

const ApmSpansLatencyHeatmapSchema = () => {
    const TracingSpansLatencyHeatmapCreateBody = orvalSchemas.TracingSpansLatencyHeatmapCreateBody()
    return TracingSpansLatencyHeatmapCreateBody
}

const apmSpansLatencyHeatmap = (): ToolBase<
    ReturnType<typeof ApmSpansLatencyHeatmapSchema>,
    Schemas._TracingLatencyHeatmapResponse
> => ({
    name: 'apm-spans-latency-heatmap',
    schema: ApmSpansLatencyHeatmapSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansLatencyHeatmapSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._TracingLatencyHeatmapResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tracing/spans/latency-heatmap/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmSpansSparklineSchema = () => {
    const TracingSpansSparklineCreateBody = orvalSchemas.TracingSpansSparklineCreateBody()
    return TracingSpansSparklineCreateBody
}

const apmSpansSparkline = (): ToolBase<ReturnType<typeof ApmSpansSparklineSchema>, unknown> => ({
    name: 'apm-spans-sparkline',
    schema: ApmSpansSparklineSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansSparklineSchema>>) => {
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

const ApmSpansTreeSchema = () => {
    const TracingSpansTreeCreateBody = orvalSchemas.TracingSpansTreeCreateBody()
    return TracingSpansTreeCreateBody
}

const apmSpansTree = (): ToolBase<ReturnType<typeof ApmSpansTreeSchema>, unknown> => ({
    name: 'apm-spans-tree',
    schema: ApmSpansTreeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ApmSpansTreeSchema>>) => {
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

const ApmTraceGetSchema = () => {
    const TracingSpansTraceCreateBody = orvalSchemas.TracingSpansTraceCreateBody()
    const TracingSpansTraceCreateParams = orvalSchemas.TracingSpansTraceCreateParams()
    return TracingSpansTraceCreateParams.omit({ project_id: true }).extend(TracingSpansTraceCreateBody.shape)
}

const apmTraceGet = (): ToolBase<ReturnType<typeof ApmTraceGetSchema>, unknown> =>
    withUiApp('trace-span-list', {
        name: 'apm-trace-get',
        schema: ApmTraceGetSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof ApmTraceGetSchema>>) => {
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
            return await withPostHogUrl(context, filtered, `/tracing?trace=${params.trace_id}`)
        },
    })

const QueryApmSpansSchema = () => {
    const TracingSpansQueryCreateBody = orvalSchemas.TracingSpansQueryCreateBody()
    return TracingSpansQueryCreateBody
}

const queryApmSpans = (): ToolBase<ReturnType<typeof QueryApmSpansSchema>, unknown> =>
    withUiApp('trace-span-list', {
        name: 'query-apm-spans',
        schema: QueryApmSpansSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof QueryApmSpansSchema>>) => {
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
    'apm-spans-latency-heatmap': apmSpansLatencyHeatmap,
    'apm-spans-sparkline': apmSpansSparkline,
    'apm-spans-tree': apmSpansTree,
    'apm-trace-get': apmTraceGet,
    'query-apm-spans': queryApmSpans,
}
