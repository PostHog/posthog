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
import type { AppMetricsResponseApi, AppMetricsTotalsResponseApi } from './api.schemas'

/**
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const getEventFilterMetricsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/event_filter/metrics/`
}

export const eventFilterMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsResponseApi> => {
    return apiMutator<AppMetricsResponseApi>(getEventFilterMetricsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const getEventFilterMetricsTotalsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/event_filter/metrics/totals/`
}

export const eventFilterMetricsTotalsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsTotalsResponseApi> => {
    return apiMutator<AppMetricsTotalsResponseApi>(getEventFilterMetricsTotalsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
