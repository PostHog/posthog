// AUTO-GENERATED from products/tracing/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    TracingSpansAttributesRetrieveQueryParams,
    TracingSpansQueryCreateBody,
    TracingSpansServiceNamesRetrieveQueryParams,
    TracingSpansTraceCreateBody,
    TracingSpansTraceCreateParams,
    TracingSpansValuesRetrieveQueryParams,
} from '@/generated/tracing/api'
import { withUiApp } from '@/resources/ui-apps'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TracingSpansAttributesRetrieveSchema = TracingSpansAttributesRetrieveQueryParams

const tracingSpansAttributesRetrieve = (): ToolBase<typeof TracingSpansAttributesRetrieveSchema, unknown> => ({
    name: 'tracing-spans-attributes-retrieve',
    schema: TracingSpansAttributesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TracingSpansAttributesRetrieveSchema>) => {
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

const TracingSpansQueryCreateSchema = TracingSpansQueryCreateBody

const tracingSpansQueryCreate = (): ToolBase<typeof TracingSpansQueryCreateSchema, unknown> =>
    withUiApp('trace-span-list', {
        name: 'tracing-spans-query-create',
        schema: TracingSpansQueryCreateSchema,
        handler: async (context: Context, params: z.infer<typeof TracingSpansQueryCreateSchema>) => {
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
            const filtered = pickResponseFields(result, ['results']) as typeof result
            return filtered
        },
    })

const TracingSpansServiceNamesRetrieveSchema = TracingSpansServiceNamesRetrieveQueryParams

const tracingSpansServiceNamesRetrieve = (): ToolBase<typeof TracingSpansServiceNamesRetrieveSchema, unknown> => ({
    name: 'tracing-spans-service-names-retrieve',
    schema: TracingSpansServiceNamesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TracingSpansServiceNamesRetrieveSchema>) => {
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

const TracingSpansTraceCreateSchema = TracingSpansTraceCreateParams.omit({ project_id: true }).extend(
    TracingSpansTraceCreateBody.shape
)

const tracingSpansTraceCreate = (): ToolBase<typeof TracingSpansTraceCreateSchema, unknown> =>
    withUiApp('trace-span-list', {
        name: 'tracing-spans-trace-create',
        schema: TracingSpansTraceCreateSchema,
        handler: async (context: Context, params: z.infer<typeof TracingSpansTraceCreateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.dateRange !== undefined) {
                body['dateRange'] = params.dateRange
            }
            const result = await context.api.request<unknown>({
                method: 'POST',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/tracing/spans/trace/${encodeURIComponent(String(params.trace_id))}/`,
                body,
            })
            const filtered = pickResponseFields(result, ['results']) as typeof result
            return filtered
        },
    })

const TracingSpansValuesRetrieveSchema = TracingSpansValuesRetrieveQueryParams

const tracingSpansValuesRetrieve = (): ToolBase<typeof TracingSpansValuesRetrieveSchema, unknown> => ({
    name: 'tracing-spans-values-retrieve',
    schema: TracingSpansValuesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof TracingSpansValuesRetrieveSchema>) => {
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'tracing-spans-attributes-retrieve': tracingSpansAttributesRetrieve,
    'tracing-spans-query-create': tracingSpansQueryCreate,
    'tracing-spans-service-names-retrieve': tracingSpansServiceNamesRetrieve,
    'tracing-spans-trace-create': tracingSpansTraceCreate,
    'tracing-spans-values-retrieve': tracingSpansValuesRetrieve,
}
