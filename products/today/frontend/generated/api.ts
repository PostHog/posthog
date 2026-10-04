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
    ExcerptChoiceApi,
    ExcerptChoiceRequestApi,
    FigureMarksApi,
    KeyClausesApi,
    KeyClausesRequestApi,
    ReportPageApi,
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

export const getTodayExcerptChoiceCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/excerpt_choice/`
}

/**
 * Asks the decision model which of several code excerpts shows what a finding describes. Returns null when it is unsure. 404 when the person may not use Jev.
 * @summary Pick the code excerpt a finding describes
 */
export const todayExcerptChoiceCreate = async (
    projectId: string,
    excerptChoiceRequestApi: ExcerptChoiceRequestApi,
    options?: RequestInit
): Promise<ExcerptChoiceApi> => {
    return apiMutator<ExcerptChoiceApi>(getTodayExcerptChoiceCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(excerptChoiceRequestApi),
    })
}

export const getTodayReportsFigureMarksRetrieveUrl = (projectId: string, reportId: string) => {
    return `/api/projects/${projectId}/today/reports/${reportId}/figure_marks/`
}

/**
 * The numbers in the report's lead and impact sentence that a signal or the agent's research states, each with the sentence that states it. A number is marked only when the decision model is sure it is a measured result and that one source states the same result. 404 when the report is missing or the person may not use Jev.
 * @summary Mark the numbers of a report with their sources
 */
export const todayReportsFigureMarksRetrieve = async (
    projectId: string,
    reportId: string,
    options?: RequestInit
): Promise<FigureMarksApi> => {
    return apiMutator<FigureMarksApi>(getTodayReportsFigureMarksRetrieveUrl(projectId, reportId), {
        ...options,
        method: 'GET',
    })
}

export const getTodayReportsKeyClausesCreateUrl = (projectId: string, reportId: string) => {
    return `/api/projects/${projectId}/today/reports/${reportId}/key_clauses/`
}

/**
 * For each text the report page shows, the clauses that state the problem, its cause or the fix, each with sentences from the report that explain it. Only clauses the report explains further are returned, at most 2 across all texts. 404 when the report is missing or the person may not use Jev.
 * @summary Mark the key clauses of a report
 */
export const todayReportsKeyClausesCreate = async (
    projectId: string,
    reportId: string,
    keyClausesRequestApi: KeyClausesRequestApi,
    options?: RequestInit
): Promise<KeyClausesApi> => {
    return apiMutator<KeyClausesApi>(getTodayReportsKeyClausesCreateUrl(projectId, reportId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(keyClausesRequestApi),
    })
}

export const getTodayReportsPageRetrieveUrl = (projectId: string, reportId: string) => {
    return `/api/projects/${projectId}/today/reports/${reportId}/page/`
}

/**
 * What the Today report page shows for a report: its lead, the proposal and the impact sentence cut to whole sentences, and the pull request it names. Sample report ids return the built-in sample reports. 404 when the report is missing or the person does not have the new navigation. 403 when the person may not read Inbox reports, and a scoped key needs task:read as well, because the page shows the report's signals.
 * @summary Get a report's page
 */
export const todayReportsPageRetrieve = async (
    projectId: string,
    reportId: string,
    options?: RequestInit
): Promise<ReportPageApi> => {
    return apiMutator<ReportPageApi>(getTodayReportsPageRetrieveUrl(projectId, reportId), {
        ...options,
        method: 'GET',
    })
}
