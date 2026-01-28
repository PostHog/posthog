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
import type {
    WebAnalyticsBreakdownResponseApi,
    WebAnalyticsBreakdownRetrieveParams,
    WebAnalyticsOverviewResponseApi,
    WebAnalyticsOverviewRetrieveParams,
} from './api.schemas'

/**
 * This endpoint is in Concept state, please join the feature preview to try it out when it's ready. Get a breakdown by a property (e.g. browser, device type, country, etc.).
 */
export const getWebAnalyticsBreakdownRetrieveUrl = (projectId: string, params: WebAnalyticsBreakdownRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/web_analytics/breakdown/?${stringifiedParams}`
        : `/api/projects/${projectId}/web_analytics/breakdown/`
}

export const webAnalyticsBreakdownRetrieve = async (
    projectId: string,
    params: WebAnalyticsBreakdownRetrieveParams,
    options?: RequestInit
): Promise<WebAnalyticsBreakdownResponseApi> => {
    return apiMutator<WebAnalyticsBreakdownResponseApi>(getWebAnalyticsBreakdownRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * This endpoint is in Concept state, please join the feature preview to try it out when it's ready. Get an overview of web analytics data including visitors, views, sessions, bounce rate, and session duration.
 */
export const getWebAnalyticsOverviewRetrieveUrl = (projectId: string, params: WebAnalyticsOverviewRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/web_analytics/overview/?${stringifiedParams}`
        : `/api/projects/${projectId}/web_analytics/overview/`
}

export const webAnalyticsOverviewRetrieve = async (
    projectId: string,
    params: WebAnalyticsOverviewRetrieveParams,
    options?: RequestInit
): Promise<WebAnalyticsOverviewResponseApi> => {
    return apiMutator<WebAnalyticsOverviewResponseApi>(getWebAnalyticsOverviewRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
