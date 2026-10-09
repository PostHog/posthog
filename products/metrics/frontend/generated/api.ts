import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AppMetricsResponseApi,
    AppMetricsTotalsResponseApi,
    DashboardImportApi,
    DashboardImportCreateApi,
    MetricsAttributeValuesRetrieveParams,
    MetricsAttributesRetrieveParams,
    MetricsCreatedDashboardApi,
    MetricsDashboardTemplateApi,
    MetricsDashboardTemplatesListParams,
    MetricsDashboardTemplatesPictureRetrieveParams,
    MetricsErrorSpikesRetrieveParams,
    MetricsNamesRetrieveParams,
    MetricsSuggestedDashboardApi,
    MetricsValuesRetrieveParams,
    PanelQueryCheckRequestApi,
    PanelQueryCheckResponseApi,
    _HasMetricsResponseApi,
    _MetricAnomalyReportApi,
    _MetricAnomalyRequestApi,
    _MetricAttributeKeysResponseApi,
    _MetricAttributeValuesResponseApi,
    _MetricCatalogValuesParamsApi,
    _MetricErrorSpikesResponseApi,
    _MetricNamesResponseApi,
    _MetricPickerNamesResponseApi,
    _MetricQueryRequestApi,
    _MetricQueryResponseApi,
    _MetricSamplesRequestApi,
    _MetricSamplesResponseApi,
    _MetricsOverviewResponseApi,
} from './api.schemas'

export const getEventFilterMetricsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_filter/metrics/`
}

/**
 * Single event filter per team.
 * GET  /event_filter/ — returns the config (or null if not yet created)
 * POST /event_filter/ — creates or updates the config (upsert)
 * GET  /event_filter/metrics/ — time-series metrics
 * GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const eventFilterMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsResponseApi> => {
    return apiMutator<AppMetricsResponseApi>(getEventFilterMetricsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventFilterMetricsTotalsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_filter/metrics/totals/`
}

/**
 * Single event filter per team.
 * GET  /event_filter/ — returns the config (or null if not yet created)
 * POST /event_filter/ — creates or updates the config (upsert)
 * GET  /event_filter/metrics/ — time-series metrics
 * GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const eventFilterMetricsTotalsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsTotalsResponseApi> => {
    return apiMutator<AppMetricsTotalsResponseApi>(getEventFilterMetricsTotalsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsAttributeValuesRetrieveUrl = (
    projectId: string,
    params: MetricsAttributeValuesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/attribute_values/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/attribute_values/`
}

/**
 * Observed values for one metric attribute key, most frequent first.
 * Backs the filter bar's value autocomplete.
 */
export const metricsAttributeValuesRetrieve = async (
    projectId: string,
    params: MetricsAttributeValuesRetrieveParams,
    options?: RequestInit
): Promise<_MetricAttributeValuesResponseApi> => {
    return apiMutator<_MetricAttributeValuesResponseApi>(getMetricsAttributeValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsAttributesRetrieveUrl = (projectId: string, params?: MetricsAttributesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/attributes/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/attributes/`
}

/**
 * Attribute keys ordered by distinct series count, from highest to
 * lowest. `metricName` limits choices to one metric.
 */
export const metricsAttributesRetrieve = async (
    projectId: string,
    params?: MetricsAttributesRetrieveParams,
    options?: RequestInit
): Promise<_MetricAttributeKeysResponseApi> => {
    return apiMutator<_MetricAttributeKeysResponseApi>(getMetricsAttributesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsCharacterizeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/characterize/`
}

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const metricsCharacterizeCreate = async (
    projectId: string,
    _metricAnomalyRequestApi: _MetricAnomalyRequestApi,
    options?: RequestInit
): Promise<_MetricAnomalyReportApi> => {
    return apiMutator<_MetricAnomalyReportApi>(getMetricsCharacterizeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricAnomalyRequestApi),
    })
}

export const getMetricsDashboardImportsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_imports/`
}

/**
 * The user's dashboard imports of the last 7 days that used the agent, with the progress of the ones that run.
 */
export const metricsDashboardImportsList = async (
    projectId: string,
    options?: RequestInit
): Promise<DashboardImportApi[]> => {
    return apiMutator<DashboardImportApi[]>(getMetricsDashboardImportsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsDashboardImportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_imports/`
}

/**
 * Import a Grafana dashboard JSON model or a dashboard screenshot as a new dashboard. Panels that match the project's metrics import at once. An AI agent converts the rest, and the response then has an id to poll.
 */
export const metricsDashboardImportsCreate = async (
    projectId: string,
    dashboardImportCreateApi: DashboardImportCreateApi,
    options?: RequestInit
): Promise<DashboardImportApi> => {
    return apiMutator<DashboardImportApi>(getMetricsDashboardImportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardImportCreateApi),
    })
}

export const getMetricsDashboardImportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_imports/${id}/`
}

/**
 * Status of one of the user's dashboard imports. Poll it until the status is not 'running'.
 */
export const metricsDashboardImportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DashboardImportApi> => {
    return apiMutator<DashboardImportApi>(getMetricsDashboardImportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsDashboardImportsValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_imports/validate/`
}

/**
 * Check dashboard panel queries before they go on a dashboard: the metrics must exist, PromQL must
 * run, and SQL must compile and read only logs or traces.
 */
export const metricsDashboardImportsValidateCreate = async (
    projectId: string,
    panelQueryCheckRequestApi: PanelQueryCheckRequestApi,
    options?: RequestInit
): Promise<PanelQueryCheckResponseApi> => {
    return apiMutator<PanelQueryCheckResponseApi>(getMetricsDashboardImportsValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(panelQueryCheckRequestApi),
    })
}

export const getMetricsDashboardTemplatesListUrl = (
    projectId: string,
    params?: MetricsDashboardTemplatesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/dashboard_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/dashboard_templates/`
}

/**
 * The templates of the metrics dashboard bank, newest first.
 */
export const metricsDashboardTemplatesList = async (
    projectId: string,
    params?: MetricsDashboardTemplatesListParams,
    options?: RequestInit
): Promise<MetricsDashboardTemplateApi[]> => {
    return apiMutator<MetricsDashboardTemplateApi[]>(getMetricsDashboardTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsDashboardTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_templates/${id}/`
}

/**
 * The metrics dashboard bank, for the PostHog staff review. The bank is instance-wide.
 */
export const metricsDashboardTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MetricsDashboardTemplateApi> => {
    return apiMutator<MetricsDashboardTemplateApi>(getMetricsDashboardTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsDashboardTemplatesApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_templates/${id}/approve/`
}

/**
 * Approve the template, so that projects whose metrics fit it see it as a suggestion.
 */
export const metricsDashboardTemplatesApproveCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MetricsDashboardTemplateApi> => {
    return apiMutator<MetricsDashboardTemplateApi>(getMetricsDashboardTemplatesApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMetricsDashboardTemplatesPictureRetrieveUrl = (
    projectId: string,
    id: string,
    params: MetricsDashboardTemplatesPictureRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/dashboard_templates/${id}/picture/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/dashboard_templates/${id}/picture/`
}

/**
 * The picture that a generation round rendered of the preview dashboard.
 */
export const metricsDashboardTemplatesPictureRetrieve = async (
    projectId: string,
    id: string,
    params: MetricsDashboardTemplatesPictureRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMetricsDashboardTemplatesPictureRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsDashboardTemplatesPreviewCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_templates/${id}/preview/`
}

/**
 * The unlisted dashboard that shows the template with this project's data. Built when it does not exist.
 * Changes on it, by hand or with PostHog AI, become the template when it is approved.
 */
export const metricsDashboardTemplatesPreviewCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MetricsCreatedDashboardApi> => {
    return apiMutator<MetricsCreatedDashboardApi>(getMetricsDashboardTemplatesPreviewCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMetricsDashboardTemplatesRejectCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_templates/${id}/reject/`
}

/**
 * Reject the template. Projects stop seeing it, and the same metrics do not generate it again.
 */
export const metricsDashboardTemplatesRejectCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MetricsDashboardTemplateApi> => {
    return apiMutator<MetricsDashboardTemplateApi>(getMetricsDashboardTemplatesRejectCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMetricsDashboardTemplatesAnalyzeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/dashboard_templates/analyze/`
}

/**
 * Analyze the metric names of this project now, and generate dashboards for new groups of metrics.
 */
export const metricsDashboardTemplatesAnalyzeCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMetricsDashboardTemplatesAnalyzeCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getMetricsErrorSpikesRetrieveUrl = (projectId: string, params: MetricsErrorSpikesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/error_spikes/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/error_spikes/`
}

/**
 * Error Tracking issue spikes detected in a time window — backs the
 * metrics chart's error-spike overlay (PoC). Team-wide: not yet scoped
 * to the metric's own service.
 */
export const metricsErrorSpikesRetrieve = async (
    projectId: string,
    params: MetricsErrorSpikesRetrieveParams,
    options?: RequestInit
): Promise<_MetricErrorSpikesResponseApi> => {
    return apiMutator<_MetricErrorSpikesResponseApi>(getMetricsErrorSpikesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsHasMetricsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/has_metrics/`
}

export const metricsHasMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<_HasMetricsResponseApi> => {
    return apiMutator<_HasMetricsResponseApi>(getMetricsHasMetricsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsNamesRetrieveUrl = (projectId: string, params?: MetricsNamesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/names/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/names/`
}

/**
 * Distinct metric names for the viewer picker, without sparklines or caching.
 */
export const metricsNamesRetrieve = async (
    projectId: string,
    params?: MetricsNamesRetrieveParams,
    options?: RequestInit
): Promise<_MetricPickerNamesResponseApi> => {
    return apiMutator<_MetricPickerNamesResponseApi>(getMetricsNamesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsOverviewRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/overview/`
}

/**
 * Ingestion rollup for the overview page: freshness of the newest
 * datapoint plus per-service metric/series counts over the last day.
 */
export const metricsOverviewRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<_MetricsOverviewResponseApi> => {
    return apiMutator<_MetricsOverviewResponseApi>(getMetricsOverviewRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/query/`
}

export const metricsQueryCreate = async (
    projectId: string,
    _metricQueryRequestApi: _MetricQueryRequestApi,
    options?: RequestInit
): Promise<_MetricQueryResponseApi> => {
    return apiMutator<_MetricQueryResponseApi>(getMetricsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricQueryRequestApi),
    })
}

export const getMetricsSamplesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/samples/`
}

/**
 * Raw individual emissions for a metric (the events model), newest
 * first — backs the Samples view and the metric->trace pivot.
 */
export const metricsSamplesCreate = async (
    projectId: string,
    _metricSamplesRequestApi: _MetricSamplesRequestApi,
    options?: RequestInit
): Promise<_MetricSamplesResponseApi> => {
    return apiMutator<_MetricSamplesResponseApi>(getMetricsSamplesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricSamplesRequestApi),
    })
}

export const getMetricsSuggestedDashboardsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/suggested_dashboards/`
}

/**
 * Dashboards from the metrics dashboard bank that suit the metrics this project sends, best fit first.
 */
export const metricsSuggestedDashboardsList = async (
    projectId: string,
    options?: RequestInit
): Promise<MetricsSuggestedDashboardApi[]> => {
    return apiMutator<MetricsSuggestedDashboardApi[]>(getMetricsSuggestedDashboardsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsSuggestedDashboardsDashboardCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/metrics/suggested_dashboards/${id}/dashboard/`
}

/**
 * Create the suggested dashboard in this project, with only the charts whose metrics the project sends.
 * A second call returns the dashboard that the first one created.
 */
export const metricsSuggestedDashboardsDashboardCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MetricsCreatedDashboardApi> => {
    return apiMutator<MetricsCreatedDashboardApi>(getMetricsSuggestedDashboardsDashboardCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMetricsValuesRetrieveUrl = (projectId: string, params?: MetricsValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/values/`
}

/**
 * Distinct metric names for the team. Backs the catalog UI.
 */
export const metricsValuesRetrieve = async (
    projectId: string,
    params?: MetricsValuesRetrieveParams,
    options?: RequestInit
): Promise<_MetricNamesResponseApi> => {
    return apiMutator<_MetricNamesResponseApi>(getMetricsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsValuesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/values/`
}

/**
 * Distinct metric names for the team. Backs the catalog UI.
 */
export const metricsValuesCreate = async (
    projectId: string,
    _metricCatalogValuesParamsApi: _MetricCatalogValuesParamsApi,
    options?: RequestInit
): Promise<_MetricNamesResponseApi> => {
    return apiMutator<_MetricNamesResponseApi>(getMetricsValuesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricCatalogValuesParamsApi),
    })
}
