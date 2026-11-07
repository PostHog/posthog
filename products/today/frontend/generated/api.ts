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
    AnalyticsSidebarApi,
    AnalyticsSidebarRequestApi,
    ExcerptChoiceApi,
    ExcerptChoiceRequestApi,
    FigureMarksApi,
    HighlightsApi,
    PulsePinsApi,
    ReportKeyClausesApi,
    ReportPageApi,
    TodayHighlightsRetrieveParams,
    TodayReportsKeyClausesRetrieveParams,
} from './api.schemas'

export const getTodayAnalyticsSidebarRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/analytics_sidebar/`
}

/**
 * The layout of the Analytics pane in the new navigation: the person's own layout, or the default when they have not saved one. Read it before you change it, so you keep the sections the person wants. 404 when the person does not have the new navigation.
 * @summary Get the person's analytics sidebar
 */
export const todayAnalyticsSidebarRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getTodayAnalyticsSidebarRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTodayAnalyticsSidebarUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/analytics_sidebar/`
}

/**
 * Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have the new navigation.
 * @summary Set the person's analytics sidebar
 */
export const todayAnalyticsSidebarUpdate = async (
    projectId: string,
    analyticsSidebarRequestApi: AnalyticsSidebarRequestApi,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getTodayAnalyticsSidebarUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(analyticsSidebarRequestApi),
    })
}

export const getTodayAnalyticsSidebarDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/analytics_sidebar/`
}

/**
 * Removes the person's own layout, so the Analytics pane shows the default again. Returns the default layout. 404 when the person does not have the new navigation.
 * @summary Reset the person's analytics sidebar
 */
export const todayAnalyticsSidebarDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getTodayAnalyticsSidebarDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
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

export const getTodayHighlightsRetrieveUrl = (projectId: string, params?: TodayHighlightsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/today/highlights/?${stringifiedParams}`
        : `/api/projects/${projectId}/today/highlights/`
}

/**
 * The project's key metrics and up to 6 ranked items, each labeled risk or opportunity. Queries, rules and copy templates make every item; no AI is used. The highlights are computed in the background and stay fresh for 15 minutes per person, or 1 minute when a source failed. The call never waits: while they are computed, it returns `computing` with the last ready highlights of the day, so poll every 2 seconds until the status is `ready` or `failed`. 404 when the person does not have the new navigation. A scoped key needs query:read as well, because every highlight runs a query.
 * @summary Get today's highlights
 */
export const todayHighlightsRetrieve = async (
    projectId: string,
    params?: TodayHighlightsRetrieveParams,
    options?: RequestInit
): Promise<HighlightsApi> => {
    return apiMutator<HighlightsApi>(getTodayHighlightsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTodayPulsePinsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/pulse_pins/`
}

/**
 * The numbers the person keeps at the start of the key numbers on their home, in order. Suggestions fill the free places. 404 when the person does not have the new navigation.
 * @summary Get the numbers the person keeps
 */
export const todayPulsePinsRetrieve = async (projectId: string, options?: RequestInit): Promise<PulsePinsApi> => {
    return apiMutator<PulsePinsApi>(getTodayPulsePinsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTodayPulsePinsUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/pulse_pins/`
}

/**
 * Replaces the numbers the person keeps at the start of the key numbers, in order. Repeated keys are dropped and only the first 4 are kept. The next highlights request computes the new numbers. 404 when the person does not have the new navigation.
 * @summary Set the numbers the person keeps
 */
export const todayPulsePinsUpdate = async (
    projectId: string,
    pulsePinsApi: PulsePinsApi,
    options?: RequestInit
): Promise<PulsePinsApi> => {
    return apiMutator<PulsePinsApi>(getTodayPulsePinsUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulsePinsApi),
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

export const getTodayReportsKeyClausesRetrieveUrl = (
    projectId: string,
    reportId: string,
    params?: TodayReportsKeyClausesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/today/reports/${reportId}/key_clauses/?${stringifiedParams}`
        : `/api/projects/${projectId}/today/reports/${reportId}/key_clauses/`
}

/**
 * The clauses in the report page's lead, impact sentence and proposal that state the problem, its cause or the fix, each with sentences from the report that explain it. Only clauses the report explains further are returned, at most 2 across all texts. 404 when the report is missing or the person may not use Jev.
 * @summary Mark the key clauses of a report
 */
export const todayReportsKeyClausesRetrieve = async (
    projectId: string,
    reportId: string,
    params?: TodayReportsKeyClausesRetrieveParams,
    options?: RequestInit
): Promise<ReportKeyClausesApi> => {
    return apiMutator<ReportKeyClausesApi>(getTodayReportsKeyClausesRetrieveUrl(projectId, reportId, params), {
        ...options,
        method: 'GET',
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
