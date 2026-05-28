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
    _MetricQueryRequestApi,
    _MetricQueryResponseApi,
} from './api.schemas'

export const getEventFilterMetricsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/event_filter/metrics/`
}

/**
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
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
    return `/api/environments/${projectId}/event_filter/metrics/totals/`
}

/**
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
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
