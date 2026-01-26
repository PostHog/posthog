/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'

export type environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponseSuccess =
    environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponse =
    environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponseSuccess

export const getEnvironmentsRevenueAnalyticsTaxonomyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/revenue_analytics/taxonomy/values/`
}

export const environmentsRevenueAnalyticsTaxonomyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponse> => {
    return apiMutator<environmentsRevenueAnalyticsTaxonomyValuesRetrieveResponse>(
        getEnvironmentsRevenueAnalyticsTaxonomyValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}
