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
    PaginatedSurveyListApi,
    PatchedSurveySerializerCreateUpdateOnlyApi,
    SurveyApi,
    SurveySerializerCreateUpdateOnlyApi,
    SurveysListParams,
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

export type surveysListResponse200 = {
    data: PaginatedSurveyListApi
    status: 200
}

export type surveysListResponseSuccess = surveysListResponse200 & {
    headers: Headers
}
export type surveysListResponse = surveysListResponseSuccess

export const getSurveysListUrl = (projectId: string, params?: SurveysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/surveys/?${stringifiedParams}`
        : `/api/projects/${projectId}/surveys/`
}

export const surveysList = async (
    projectId: string,
    params?: SurveysListParams,
    options?: RequestInit
): Promise<surveysListResponse> => {
    return apiMutator<surveysListResponse>(getSurveysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type surveysCreateResponse201 = {
    data: SurveySerializerCreateUpdateOnlyApi
    status: 201
}

export type surveysCreateResponseSuccess = surveysCreateResponse201 & {
    headers: Headers
}
export type surveysCreateResponse = surveysCreateResponseSuccess

export const getSurveysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/`
}

export const surveysCreate = async (
    projectId: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysCreateResponse> => {
    return apiMutator<surveysCreateResponse>(getSurveysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export type surveysRetrieveResponse200 = {
    data: SurveyApi
    status: 200
}

export type surveysRetrieveResponseSuccess = surveysRetrieveResponse200 & {
    headers: Headers
}
export type surveysRetrieveResponse = surveysRetrieveResponseSuccess

export const getSurveysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<surveysRetrieveResponse> => {
    return apiMutator<surveysRetrieveResponse>(getSurveysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type surveysUpdateResponse200 = {
    data: SurveyApi
    status: 200
}

export type surveysUpdateResponseSuccess = surveysUpdateResponse200 & {
    headers: Headers
}
export type surveysUpdateResponse = surveysUpdateResponseSuccess

export const getSurveysUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysUpdate = async (
    projectId: string,
    id: string,
    surveyApi: NonReadonly<SurveyApi>,
    options?: RequestInit
): Promise<surveysUpdateResponse> => {
    return apiMutator<surveysUpdateResponse>(getSurveysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveyApi),
    })
}

export type surveysPartialUpdateResponse200 = {
    data: SurveySerializerCreateUpdateOnlyApi
    status: 200
}

export type surveysPartialUpdateResponseSuccess = surveysPartialUpdateResponse200 & {
    headers: Headers
}
export type surveysPartialUpdateResponse = surveysPartialUpdateResponseSuccess

export const getSurveysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSurveySerializerCreateUpdateOnlyApi: NonReadonly<PatchedSurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysPartialUpdateResponse> => {
    return apiMutator<surveysPartialUpdateResponse>(getSurveysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSurveySerializerCreateUpdateOnlyApi),
    })
}

export type surveysDestroyResponse204 = {
    data: void
    status: 204
}

export type surveysDestroyResponseSuccess = surveysDestroyResponse204 & {
    headers: Headers
}
export type surveysDestroyResponse = surveysDestroyResponseSuccess

export const getSurveysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<surveysDestroyResponse> => {
    return apiMutator<surveysDestroyResponse>(getSurveysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type surveysActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type surveysActivityRetrieve2ResponseSuccess = surveysActivityRetrieve2Response200 & {
    headers: Headers
}
export type surveysActivityRetrieve2Response = surveysActivityRetrieve2ResponseSuccess

export const getSurveysActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/activity/`
}

export const surveysActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<surveysActivityRetrieve2Response> => {
    return apiMutator<surveysActivityRetrieve2Response>(getSurveysActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get list of archived response UUIDs for HogQL filtering.

Returns list of UUIDs that the frontend can use to filter out archived responses
in HogQL queries.
 */
export type surveysArchivedResponseUuidsRetrieveResponse200 = {
    data: void
    status: 200
}

export type surveysArchivedResponseUuidsRetrieveResponseSuccess = surveysArchivedResponseUuidsRetrieveResponse200 & {
    headers: Headers
}
export type surveysArchivedResponseUuidsRetrieveResponse = surveysArchivedResponseUuidsRetrieveResponseSuccess

export const getSurveysArchivedResponseUuidsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/archived-response-uuids/`
}

export const surveysArchivedResponseUuidsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<surveysArchivedResponseUuidsRetrieveResponse> => {
    return apiMutator<surveysArchivedResponseUuidsRetrieveResponse>(
        getSurveysArchivedResponseUuidsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Duplicate a survey to multiple projects in a single transaction.

Accepts a list of target team IDs and creates a copy of the survey in each project.
Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
 */
export type surveysDuplicateToProjectsCreateResponse200 = {
    data: void
    status: 200
}

export type surveysDuplicateToProjectsCreateResponseSuccess = surveysDuplicateToProjectsCreateResponse200 & {
    headers: Headers
}
export type surveysDuplicateToProjectsCreateResponse = surveysDuplicateToProjectsCreateResponseSuccess

export const getSurveysDuplicateToProjectsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/duplicate_to_projects/`
}

export const surveysDuplicateToProjectsCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysDuplicateToProjectsCreateResponse> => {
    return apiMutator<surveysDuplicateToProjectsCreateResponse>(getSurveysDuplicateToProjectsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

/**
 * Archive a single survey response.
 */
export type surveysResponsesArchiveCreateResponse200 = {
    data: void
    status: 200
}

export type surveysResponsesArchiveCreateResponseSuccess = surveysResponsesArchiveCreateResponse200 & {
    headers: Headers
}
export type surveysResponsesArchiveCreateResponse = surveysResponsesArchiveCreateResponseSuccess

export const getSurveysResponsesArchiveCreateUrl = (projectId: string, id: string, responseUuid: string) => {
    return `/api/projects/${projectId}/surveys/${id}/responses/${responseUuid}/archive/`
}

export const surveysResponsesArchiveCreate = async (
    projectId: string,
    id: string,
    responseUuid: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysResponsesArchiveCreateResponse> => {
    return apiMutator<surveysResponsesArchiveCreateResponse>(
        getSurveysResponsesArchiveCreateUrl(projectId, id, responseUuid),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
        }
    )
}

/**
 * Unarchive a single survey response.
 */
export type surveysResponsesUnarchiveCreateResponse200 = {
    data: void
    status: 200
}

export type surveysResponsesUnarchiveCreateResponseSuccess = surveysResponsesUnarchiveCreateResponse200 & {
    headers: Headers
}
export type surveysResponsesUnarchiveCreateResponse = surveysResponsesUnarchiveCreateResponseSuccess

export const getSurveysResponsesUnarchiveCreateUrl = (projectId: string, id: string, responseUuid: string) => {
    return `/api/projects/${projectId}/surveys/${id}/responses/${responseUuid}/unarchive/`
}

export const surveysResponsesUnarchiveCreate = async (
    projectId: string,
    id: string,
    responseUuid: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysResponsesUnarchiveCreateResponse> => {
    return apiMutator<surveysResponsesUnarchiveCreateResponse>(
        getSurveysResponsesUnarchiveCreateUrl(projectId, id, responseUuid),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
        }
    )
}

/**
 * Get survey response statistics for a specific survey.

Args:
    date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
    exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)

Returns:
    Survey statistics including event counts, unique respondents, and conversion rates
 */
export type surveysStatsRetrieve2Response200 = {
    data: void
    status: 200
}

export type surveysStatsRetrieve2ResponseSuccess = surveysStatsRetrieve2Response200 & {
    headers: Headers
}
export type surveysStatsRetrieve2Response = surveysStatsRetrieve2ResponseSuccess

export const getSurveysStatsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/stats/`
}

export const surveysStatsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<surveysStatsRetrieve2Response> => {
    return apiMutator<surveysStatsRetrieve2Response>(getSurveysStatsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type surveysSummarizeResponsesCreateResponse200 = {
    data: void
    status: 200
}

export type surveysSummarizeResponsesCreateResponseSuccess = surveysSummarizeResponsesCreateResponse200 & {
    headers: Headers
}
export type surveysSummarizeResponsesCreateResponse = surveysSummarizeResponsesCreateResponseSuccess

export const getSurveysSummarizeResponsesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/summarize_responses/`
}

export const surveysSummarizeResponsesCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysSummarizeResponsesCreateResponse> => {
    return apiMutator<surveysSummarizeResponsesCreateResponse>(getSurveysSummarizeResponsesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export type surveysSummaryHeadlineCreateResponse200 = {
    data: void
    status: 200
}

export type surveysSummaryHeadlineCreateResponseSuccess = surveysSummaryHeadlineCreateResponse200 & {
    headers: Headers
}
export type surveysSummaryHeadlineCreateResponse = surveysSummaryHeadlineCreateResponseSuccess

export const getSurveysSummaryHeadlineCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/summary_headline/`
}

export const surveysSummaryHeadlineCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<surveysSummaryHeadlineCreateResponse> => {
    return apiMutator<surveysSummaryHeadlineCreateResponse>(getSurveysSummaryHeadlineCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export type surveysActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type surveysActivityRetrieveResponseSuccess = surveysActivityRetrieveResponse200 & {
    headers: Headers
}
export type surveysActivityRetrieveResponse = surveysActivityRetrieveResponseSuccess

export const getSurveysActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/activity/`
}

export const surveysActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<surveysActivityRetrieveResponse> => {
    return apiMutator<surveysActivityRetrieveResponse>(getSurveysActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get response counts for all surveys.

Args:
    exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)
    survey_ids: Optional comma-separated list of survey IDs to filter by

Returns:
    Dictionary mapping survey IDs to response counts
 */
export type surveysResponsesCountRetrieveResponse200 = {
    data: void
    status: 200
}

export type surveysResponsesCountRetrieveResponseSuccess = surveysResponsesCountRetrieveResponse200 & {
    headers: Headers
}
export type surveysResponsesCountRetrieveResponse = surveysResponsesCountRetrieveResponseSuccess

export const getSurveysResponsesCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/responses_count/`
}

export const surveysResponsesCountRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<surveysResponsesCountRetrieveResponse> => {
    return apiMutator<surveysResponsesCountRetrieveResponse>(getSurveysResponsesCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get aggregated response statistics across all surveys.

Args:
    date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)

Returns:
    Aggregated statistics across all surveys including total counts and rates
 */
export type surveysStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type surveysStatsRetrieveResponseSuccess = surveysStatsRetrieveResponse200 & {
    headers: Headers
}
export type surveysStatsRetrieveResponse = surveysStatsRetrieveResponseSuccess

export const getSurveysStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/stats/`
}

export const surveysStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<surveysStatsRetrieveResponse> => {
    return apiMutator<surveysStatsRetrieveResponse>(getSurveysStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
