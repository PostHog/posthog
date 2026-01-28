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
): Promise<PaginatedSurveyListApi> => {
    return apiMutator<PaginatedSurveyListApi>(getSurveysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSurveysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/`
}

export const surveysCreate = async (
    projectId: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<SurveySerializerCreateUpdateOnlyApi> => {
    return apiMutator<SurveySerializerCreateUpdateOnlyApi>(getSurveysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export const getSurveysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<SurveyApi> => {
    return apiMutator<SurveyApi>(getSurveysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSurveysUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysUpdate = async (
    projectId: string,
    id: string,
    surveyApi: NonReadonly<SurveyApi>,
    options?: RequestInit
): Promise<SurveyApi> => {
    return apiMutator<SurveyApi>(getSurveysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveyApi),
    })
}

export const getSurveysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSurveySerializerCreateUpdateOnlyApi: NonReadonly<PatchedSurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<SurveySerializerCreateUpdateOnlyApi> => {
    return apiMutator<SurveySerializerCreateUpdateOnlyApi>(getSurveysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSurveySerializerCreateUpdateOnlyApi),
    })
}

export const getSurveysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/`
}

export const surveysDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSurveysActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/activity/`
}

export const surveysActivityRetrieve2 = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get list of archived response UUIDs for HogQL filtering.

Returns list of UUIDs that the frontend can use to filter out archived responses
in HogQL queries.
 */
export const getSurveysArchivedResponseUuidsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/archived-response-uuids/`
}

export const surveysArchivedResponseUuidsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysArchivedResponseUuidsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Duplicate a survey to multiple projects in a single transaction.

Accepts a list of target team IDs and creates a copy of the survey in each project.
Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
 */
export const getSurveysDuplicateToProjectsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/duplicate_to_projects/`
}

export const surveysDuplicateToProjectsCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysDuplicateToProjectsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

/**
 * Archive a single survey response.
 */
export const getSurveysResponsesArchiveCreateUrl = (projectId: string, id: string, responseUuid: string) => {
    return `/api/projects/${projectId}/surveys/${id}/responses/${responseUuid}/archive/`
}

export const surveysResponsesArchiveCreate = async (
    projectId: string,
    id: string,
    responseUuid: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysResponsesArchiveCreateUrl(projectId, id, responseUuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

/**
 * Unarchive a single survey response.
 */
export const getSurveysResponsesUnarchiveCreateUrl = (projectId: string, id: string, responseUuid: string) => {
    return `/api/projects/${projectId}/surveys/${id}/responses/${responseUuid}/unarchive/`
}

export const surveysResponsesUnarchiveCreate = async (
    projectId: string,
    id: string,
    responseUuid: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysResponsesUnarchiveCreateUrl(projectId, id, responseUuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
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
export const getSurveysStatsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/stats/`
}

export const surveysStatsRetrieve2 = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysStatsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSurveysSummarizeResponsesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/summarize_responses/`
}

export const surveysSummarizeResponsesCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysSummarizeResponsesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export const getSurveysSummaryHeadlineCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/surveys/${id}/summary_headline/`
}

export const surveysSummaryHeadlineCreate = async (
    projectId: string,
    id: string,
    surveySerializerCreateUpdateOnlyApi: NonReadonly<SurveySerializerCreateUpdateOnlyApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSurveysSummaryHeadlineCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(surveySerializerCreateUpdateOnlyApi),
    })
}

export const getSurveysActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/activity/`
}

export const surveysActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysActivityRetrieveUrl(projectId), {
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
export const getSurveysResponsesCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/responses_count/`
}

export const surveysResponsesCountRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysResponsesCountRetrieveUrl(projectId), {
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
export const getSurveysStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/surveys/stats/`
}

export const surveysStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSurveysStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
