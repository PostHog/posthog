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
    MetricsHasMetricsRetrieve200,
    MetricsValuesRetrieveParams,
    _MetricAnomalyReportApi,
    _MetricAnomalyRequestApi,
    _MetricNamesResponseApi,
    _MetricQueryRequestApi,
    _MetricQueryResponseApi,
    _MetricSamplesRequestApi,
    _MetricSamplesResponseApi,
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

export const getMetricsHasMetricsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/has_metrics/`
}

export const metricsHasMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<MetricsHasMetricsRetrieve200> => {
    return apiMutator<MetricsHasMetricsRetrieve200>(getMetricsHasMetricsRetrieveUrl(projectId), {
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
 * Distinct metric names for the team. Backs the picker UI.
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
