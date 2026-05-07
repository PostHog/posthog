// AUTO-GENERATED from products/tracing/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ObservabilitySignalSnapshotCreateBody,
    TracingSpansAttributesRetrieveQueryParams,
    TracingSpansQueryCreateBody,
    TracingSpansServiceNamesRetrieveQueryParams,
    TracingSpansSparklineCreateBody,
    TracingSpansTraceCreateBody,
    TracingSpansTraceCreateParams,
    TracingSpansValuesRetrieveQueryParams,
} from '@/generated/tracing/api'
import { withUiApp } from '@/resources/ui-apps'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ApmAttributeValuesListSchema = TracingSpansValuesRetrieveQueryParams

const apmAttributeValuesList = (): ToolBase<typeof ApmAttributeValuesListSchema, unknown> => ({
    name: 'apm-attribute-values-list',
    schema: ApmAttributeValuesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApmAttributeValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/values/`,
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

const apmAttributesList = (): ToolBase<typeof ApmAttributesListSchema, unknown> => ({
    name: 'apm-attributes-list',
    schema: ApmAttributesListSchema,
    handler: async (context: Context, params: z.infer<typeof ApmAttributesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/attributes/`,
            query: {
                attribute_type: params.attribute_type,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
        return filtered
    },
})

const ApmLogsSignalSnapshotSchema = ObservabilitySignalSnapshotCreateBody

const apmLogsSignalSnapshot = (): ToolBase<
    typeof ApmLogsSignalSnapshotSchema,
    Schemas.ObservabilitySignalSnapshotResponse
> => ({
    name: 'apm-logs-signal-snapshot',
    schema: ApmLogsSignalSnapshotSchema,
    handler: async (context: Context, params: z.infer<typeof ApmLogsSignalSnapshotSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.dateRange !== undefined) {
            body['dateRange'] = params.dateRange
        }
        if (params.serviceNames !== undefined) {
            body['serviceNames'] = params.serviceNames
        }
        const result = await context.api.request<Schemas.ObservabilitySignalSnapshotResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/observability/signal-snapshot/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'resolvedDateRange',
            'logServiceNames',
            'traceServiceNames',
            'serviceNamesOverlap',
            'logOnlyServiceNames',
            'traceOnlyServiceNames',
            'logsTotal',
            'logsWithJoinableTraceId',
            'joinableTraceIdPercent',
            'sampleJoinableTraceIds',
        ]) as typeof result
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/service-names/`,
            query: {
                dateRange: params.dateRange,
                search: params.search,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const ApmSparklineQuerySchema = TracingSpansSparklineCreateBody

const apmSparklineQuery = (): ToolBase<typeof ApmSparklineQuerySchema, unknown> => ({
    name: 'apm-sparkline-query',
    schema: ApmSparklineQuerySchema,
    handler: async (context: Context, params: z.infer<typeof ApmSparklineQuerySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/sparkline/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
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
            if (params.maxSpans !== undefined) {
                body['maxSpans'] = params.maxSpans
            }
            const result = await context.api.request<unknown>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/trace/${encodeURIComponent(String(params.trace_id))}/`,
                body,
            })
            const filtered = pickResponseFields(result, ['results', 'truncated', 'maxSpans']) as typeof result
            return filtered
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
                path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/query/`,
                body,
            })
            const filtered = pickResponseFields(result, [
                'results',
                'hasMore',
                'nextCursor',
                'resultCount',
                'warnings',
                'resolvedDateRange',
                'exemplarTraceIds',
            ]) as typeof result
            return filtered
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'apm-attribute-values-list': apmAttributeValuesList,
    'apm-attributes-list': apmAttributesList,
    'apm-logs-signal-snapshot': apmLogsSignalSnapshot,
    'apm-services-list': apmServicesList,
    'apm-sparkline-query': apmSparklineQuery,
    'apm-trace-get': apmTraceGet,
    'query-apm-spans': queryApmSpans,
}
