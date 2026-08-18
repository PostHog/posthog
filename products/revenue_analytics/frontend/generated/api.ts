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
import type { RevenueAnalyticsJoinApi, RevenueAnalyticsJoinResponseApi } from './api.schemas'

export const getRevenueAnalyticsJoinsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/revenue_analytics/joins/`
}

export const revenueAnalyticsJoinsCreate = async (
    projectId: string,
    revenueAnalyticsJoinApi: RevenueAnalyticsJoinApi,
    options?: RequestInit
): Promise<RevenueAnalyticsJoinResponseApi> => {
    return apiMutator<RevenueAnalyticsJoinResponseApi>(getRevenueAnalyticsJoinsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(revenueAnalyticsJoinApi),
    })
}

export const getRevenueAnalyticsTaxonomyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/revenue_analytics/taxonomy/values/`
}

export const revenueAnalyticsTaxonomyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getRevenueAnalyticsTaxonomyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
