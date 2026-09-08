// AUTO-GENERATED from products/metrics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/metrics/api'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CharacterizeMetricAnomalySchema = () => {
    const MetricsCharacterizeCreateBody = orvalSchemas.MetricsCharacterizeCreateBody()
    return MetricsCharacterizeCreateBody
}

const characterizeMetricAnomaly = (): ToolBase<
    ReturnType<typeof CharacterizeMetricAnomalySchema>,
    Schemas._MetricAnomalyReport
> => ({
    name: 'characterize-metric-anomaly',
    schema: CharacterizeMetricAnomalySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CharacterizeMetricAnomalySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._MetricAnomalyReport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/characterize/`,
            body,
        })
        return result
    },
})

const MetricNamesListSchema = () => {
    const MetricsValuesRetrieveQueryParams = orvalSchemas.MetricsValuesRetrieveQueryParams()
    return MetricsValuesRetrieveQueryParams
}

const metricNamesList = (): ToolBase<ReturnType<typeof MetricNamesListSchema>, Schemas._MetricNamesResponse> => ({
    name: 'metric-names-list',
    schema: MetricNamesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MetricNamesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._MetricNamesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/values/`,
            query: {
                limit: params.limit,
                service: params.service,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const QueryMetricsSchema = () => {
    const MetricsQueryCreateBody = orvalSchemas.MetricsQueryCreateBody()
    return MetricsQueryCreateBody
}

const queryMetrics = (): ToolBase<ReturnType<typeof QueryMetricsSchema>, Schemas._MetricQueryResponse> => ({
    name: 'query-metrics',
    schema: QueryMetricsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof QueryMetricsSchema>>) => {
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
    'characterize-metric-anomaly': characterizeMetricAnomaly,
    'metric-names-list': metricNamesList,
    'query-metrics': queryMetrics,
}
