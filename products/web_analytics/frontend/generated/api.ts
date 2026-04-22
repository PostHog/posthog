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
import type { WebAnalyticsWeeklyDigestParams, WeeklyDigestResponseApi } from './api.schemas'

/**
 * Summarizes a project's web analytics over a lookback window (default 7 days): unique visitors, pageviews, sessions, bounce rate, and average session duration with period-over-period comparisons, plus the top 5 pages, top 5 traffic sources, and goal conversions.
 * @summary Summarize web analytics
 */
export const getWebAnalyticsWeeklyDigestUrl = (projectId: string, params?: WebAnalyticsWeeklyDigestParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/web_analytics/weekly_digest/?${stringifiedParams}`
        : `/api/environments/${projectId}/web_analytics/weekly_digest/`
}

export const webAnalyticsWeeklyDigest = async (
    projectId: string,
    params?: WebAnalyticsWeeklyDigestParams,
    options?: RequestInit
): Promise<WeeklyDigestResponseApi> => {
    return apiMutator<WeeklyDigestResponseApi>(getWebAnalyticsWeeklyDigestUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
