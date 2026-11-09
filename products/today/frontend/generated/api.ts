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
    ExcerptChoiceApi,
    ExcerptChoiceRequestApi,
    FigureMarksApi,
    HiddenPulseNumbersApi,
    HighlightsApi,
    PulsePinsApi,
    ReportKeyClausesApi,
    ReportPageApi,
    SetHiddenPulseNumbersApi,
    TodayHighlightsRetrieveParams,
    TodayNewsApi,
    TodayReportsKeyClausesRetrieveParams,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

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

export const getTodayNewsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/news/`
}

/**
 * Today's news edition for the whole project: a lead story, up to 4 more stories, ongoing stories, the trends of the week and briefs. An AI agent writes one edition per project and day, from the last 24 hours, when the first person opens the news with `news/write`. This call never starts it. `ready` returns today's edition. `not_started`, `computing` and `failed` return the latest earlier edition, or null, so poll every 5 seconds while the status is `computing`. Stories about data the person cannot see are left out. `skipped` with a reason when the day was quiet, AI data processing is off, or fewer than 2 people use Today. 404 when the person does not have the news.
 * @summary Get today's project news
 */
export const todayNewsRetrieve = async (projectId: string, options?: RequestInit): Promise<TodayNewsApi> => {
    return apiMutator<TodayNewsApi>(getTodayNewsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTodayNewsWriteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/news/write/`
}

/**
 * Starts the AI agent that writes today's edition and returns `computing`. Writing takes a few minutes, so poll the news every 5 seconds while the status is `computing`. It starts at most one run per project and day, and tries again only after a failed run is an hour old. It starts nothing when the edition is ready, the daily limit is reached, or AI data processing is off, and then returns the same as the news call. 404 when the person does not have the news.
 * @summary Start writing today's news
 */
export const todayNewsWriteCreate = async (projectId: string, options?: RequestInit): Promise<TodayNewsApi> => {
    return apiMutator<TodayNewsApi>(getTodayNewsWriteCreateUrl(projectId), {
        ...options,
        method: 'POST',
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
    pulsePinsApi: NonReadonly<PulsePinsApi>,
    options?: RequestInit
): Promise<PulsePinsApi> => {
    return apiMutator<PulsePinsApi>(getTodayPulsePinsUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pulsePinsApi),
    })
}

export const getTodayPulsePinsHiddenUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/today/pulse_pins/hidden/`
}

/**
 * Replaces the numbers the person hid from the key numbers. Suggestions skip them, so the next highlights request computes other numbers in their places. Repeated keys are dropped and only the last 50 are kept. 404 when the person does not have the new navigation.
 * @summary Set the numbers the person hid
 */
export const todayPulsePinsHiddenUpdate = async (
    projectId: string,
    setHiddenPulseNumbersApi: SetHiddenPulseNumbersApi,
    options?: RequestInit
): Promise<HiddenPulseNumbersApi> => {
    return apiMutator<HiddenPulseNumbersApi>(getTodayPulsePinsHiddenUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setHiddenPulseNumbersApi),
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
