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
import type { MarketingAnalyticsUtmAuditRetrieveParams, UtmAuditResponseApi } from './api.schemas'

export const getMarketingAnalyticsTestMappingCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/marketing_analytics/test_mapping/`
}

export const marketingAnalyticsTestMappingCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMarketingAnalyticsTestMappingCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.
 * @summary Run UTM audit
 */
export const getMarketingAnalyticsUtmAuditRetrieveUrl = (
    projectId: string,
    params?: MarketingAnalyticsUtmAuditRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/marketing_analytics/utm_audit/?${stringifiedParams}`
        : `/api/environments/${projectId}/marketing_analytics/utm_audit/`
}

export const marketingAnalyticsUtmAuditRetrieve = async (
    projectId: string,
    params?: MarketingAnalyticsUtmAuditRetrieveParams,
    options?: RequestInit
): Promise<UtmAuditResponseApi> => {
    return apiMutator<UtmAuditResponseApi>(getMarketingAnalyticsUtmAuditRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
