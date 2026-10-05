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
    BriefingApi,
    CandidateListApi,
    TodayBriefingRefreshCreateParams,
    TodayBriefingRetrieveParams,
    TodayCandidatesRetrieveParams,
} from './api.schemas'

export const getTodayBriefingRetrieveUrl = (projectId: string, params?: TodayBriefingRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/today/briefing/?${stringifiedParams}`
        : `/api/projects/${projectId}/today/briefing/`
}

/**
 * Today's personal briefing: a short text about up to 5 items and the same items for the left bar. A new one is written every morning from 8:00 local time. Starts generating today's when there is none yet and returns it as 'collecting'. While a refresh is being written, the ready briefing is returned as 'writing', so it can stay on screen; poll again after a few seconds. 404 when the person gets no briefing: the flag is off, the organization has not approved AI data processing, or it is out of AI credits.
 * @summary Get today's briefing
 */
export const todayBriefingRetrieve = async (
    projectId: string,
    params?: TodayBriefingRetrieveParams,
    options?: RequestInit
): Promise<BriefingApi> => {
    return apiMutator<BriefingApi>(getTodayBriefingRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTodayBriefingRefreshCreateUrl = (projectId: string, params?: TodayBriefingRefreshCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/today/briefing/refresh/?${stringifiedParams}`
        : `/api/projects/${projectId}/today/briefing/refresh/`
}

/**
 * Regenerate today's briefing. The ready briefing stays on screen until the new one is written.
 * @summary Refresh today's briefing
 */
export const todayBriefingRefreshCreate = async (
    projectId: string,
    params?: TodayBriefingRefreshCreateParams,
    options?: RequestInit
): Promise<BriefingApi> => {
    return apiMutator<BriefingApi>(getTodayBriefingRefreshCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
    })
}

export const getTodayCandidatesRetrieveUrl = (projectId: string, params?: TodayCandidatesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/today/candidates/?${stringifiedParams}`
        : `/api/projects/${projectId}/today/candidates/`
}

/**
 * The items behind today's briefing, with the facts and the reason for each, without the written text.
 * @summary List today's ranked items
 */
export const todayCandidatesRetrieve = async (
    projectId: string,
    params?: TodayCandidatesRetrieveParams,
    options?: RequestInit
): Promise<CandidateListApi> => {
    return apiMutator<CandidateListApi>(getTodayCandidatesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
