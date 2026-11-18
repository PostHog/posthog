// AUTO-GENERATED from products/metrics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/metrics/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
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

const MetricAttributeValuesListSchema = () => {
    const MetricsAttributeValuesRetrieveQueryParams = orvalSchemas.MetricsAttributeValuesRetrieveQueryParams()
    return MetricsAttributeValuesRetrieveQueryParams
}

const metricAttributeValuesList = (): ToolBase<
    ReturnType<typeof MetricAttributeValuesListSchema>,
    Schemas._MetricAttributeValuesResponse
> => ({
    name: 'metric-attribute-values-list',
    schema: MetricAttributeValuesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MetricAttributeValuesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._MetricAttributeValuesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/attribute_values/`,
            query: {
                dateFrom: params.dateFrom,
                dateTo: params.dateTo,
                key: params.key,
                limit: params.limit,
                metricName: params.metricName,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const MetricAttributesListSchema = () => {
    const MetricsAttributesRetrieveQueryParams = orvalSchemas.MetricsAttributesRetrieveQueryParams()
    return MetricsAttributesRetrieveQueryParams
}

const metricAttributesList = (): ToolBase<
    ReturnType<typeof MetricAttributesListSchema>,
    Schemas._MetricAttributeKeysResponse
> => ({
    name: 'metric-attributes-list',
    schema: MetricAttributesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MetricAttributesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._MetricAttributeKeysResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/attributes/`,
            query: {
                dateFrom: params.dateFrom,
                dateTo: params.dateTo,
                limit: params.limit,
                metricName: params.metricName,
                search: params.search,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const MetricNamesListSchema = () => {
    const MetricsValuesRetrieveQueryParams = orvalSchemas.MetricsValuesRetrieveQueryParams()
    return MetricsValuesRetrieveQueryParams.extend({
        limit: MetricsValuesRetrieveQueryParams.shape['limit']
            .default(50)
            .optional()
            .describe('Max names to return, 1 to 1000. Defaults to 50.'),
        sparklines: MetricsValuesRetrieveQueryParams.shape['sparklines']
            .default(false)
            .optional()
            .describe(
                'Attach a 24-point sparkline of the last 6 hours to each name. Defaults to false; turn on only when you need the recent shape, since it makes the response several times larger.'
            ),
        first_seen: MetricsValuesRetrieveQueryParams.shape['first_seen']
            .default(true)
            .optional()
            .describe('Add `first_seen`, the earliest hour each name arrived in within retention. Defaults to true.'),
        fold_histograms: MetricsValuesRetrieveQueryParams.shape['fold_histograms']
            .default(true)
            .optional()
            .describe(
                "Fold a Prometheus classic histogram's `_bucket`, `_sum` and `_count` names into one `_bucket` entry with `classic_histogram` set. Defaults to true."
            ),
    })
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
                first_seen: params.first_seen,
                fold_histograms: params.fold_histograms,
                limit: params.limit,
                match: params.match,
                service: params.service,
                sparklines: params.sparklines,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const MetricsDashboardPanelsValidateSchema = () => {
    const MetricsDashboardImportsValidateCreateBody = orvalSchemas.MetricsDashboardImportsValidateCreateBody()
    return MetricsDashboardImportsValidateCreateBody
}

const metricsDashboardPanelsValidate = (): ToolBase<
    ReturnType<typeof MetricsDashboardPanelsValidateSchema>,
    Schemas.PanelQueryCheckResponse
> => ({
    name: 'metrics-dashboard-panels-validate',
    schema: MetricsDashboardPanelsValidateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MetricsDashboardPanelsValidateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.panels !== undefined) {
            body['panels'] = params.panels
        }
        if (params.import_id !== undefined) {
            body['import_id'] = params.import_id
        }
        const result = await context.api.request<Schemas.PanelQueryCheckResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/metrics/dashboard_imports/validate/`,
            body,
        })
        return result
    },
})

const QueryMetricsSchema = () => {
    const MetricsQueryCreateBody = orvalSchemas.MetricsQueryCreateBody()
    return MetricsQueryCreateBody
}

const queryMetrics = (): ToolBase<
    ReturnType<typeof QueryMetricsSchema>,
    WithPostHogUrl<Schemas._MetricQueryResponse>
> => ({
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
        const filtered = pickResponseFields(result, [
            'results',
            'hint',
            'omitted_empty_series',
            'omitted_by_limit',
            'url_params',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/metrics?${filtered.url_params}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'characterize-metric-anomaly': characterizeMetricAnomaly,
    'metric-attribute-values-list': metricAttributeValuesList,
    'metric-attributes-list': metricAttributesList,
    'metric-names-list': metricNamesList,
    'metrics-dashboard-panels-validate': metricsDashboardPanelsValidate,
    'query-metrics': queryMetrics,
}
