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
    BriefingWriteApi,
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
 * Today's personal briefing: a short text about the top 5 items and a left bar with the top 10. There are two editions a day, from 8:00 and from 12:00 local time. Starts generating the current edition when there is none yet; while it writes, the template draft is returned with status 'writing'.
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
 * Regenerate the current edition of today's briefing. The ready briefing stays on screen until the new one is written.
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

export const getTodayBriefingWriteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/briefing/write/`
}

/**
 * Store the text and the items of a briefing that is being generated for the current user. Only the briefing named in the generation prompt can be written. The text must link every item exactly once, highlight only the first item, keep labels to 6 words and signals to 40 characters, and use no em or en dashes; a 400 lists every rule the text broke so it can be fixed and sent again.
 * @summary Write today's briefing
 */
export const todayBriefingWriteCreate = async (
    projectId: string,
    briefingWriteApi: BriefingWriteApi,
    options?: RequestInit
): Promise<BriefingApi> => {
    return apiMutator<BriefingApi>(getTodayBriefingWriteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(briefingWriteApi),
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
 * The ranked items behind today's briefing, with the facts and the reason for each, without the written text.
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
