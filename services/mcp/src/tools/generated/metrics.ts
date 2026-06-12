// AUTO-GENERATED from products/metrics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { MetricsQueryCreateBody, MetricsValuesRetrieveQueryParams } from '@/generated/metrics/api'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MetricNamesListSchema = MetricsValuesRetrieveQueryParams

const metricNamesList = (): ToolBase<typeof MetricNamesListSchema, Schemas._MetricNamesResponse> => ({
    name: 'metric-names-list',
    schema: MetricNamesListSchema,
    handler: async (context: Context, params: z.infer<typeof MetricNamesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._MetricNamesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/values/`,
            query: {
                limit: params.limit,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const QueryMetricsSchema = MetricsQueryCreateBody

const queryMetrics = (): ToolBase<typeof QueryMetricsSchema, Schemas._MetricQueryResponse> => ({
    name: 'query-metrics',
    schema: QueryMetricsSchema,
    handler: async (context: Context, params: z.infer<typeof QueryMetricsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._MetricQueryResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/query/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'metric-names-list': metricNamesList,
    'query-metrics': queryMetrics,
}
