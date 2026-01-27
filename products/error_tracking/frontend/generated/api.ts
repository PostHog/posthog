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
    ErrorTrackingAssignmentRuleApi,
    ErrorTrackingAssignmentRulesListParams,
    ErrorTrackingExternalReferenceApi,
    ErrorTrackingExternalReferencesListParams,
    ErrorTrackingFingerprintApi,
    ErrorTrackingFingerprintsListParams,
    ErrorTrackingGroupingRuleApi,
    ErrorTrackingGroupingRulesListParams,
    ErrorTrackingIssueFullApi,
    ErrorTrackingIssuesListParams,
    ErrorTrackingReleaseApi,
    ErrorTrackingReleasesList2Params,
    ErrorTrackingReleasesListParams,
    ErrorTrackingStackFrameApi,
    ErrorTrackingStackFramesListParams,
    ErrorTrackingSuppressionRuleApi,
    ErrorTrackingSuppressionRulesListParams,
    ErrorTrackingSymbolSetApi,
    ErrorTrackingSymbolSetsList2Params,
    ErrorTrackingSymbolSetsListParams,
    PaginatedErrorTrackingAssignmentRuleListApi,
    PaginatedErrorTrackingExternalReferenceListApi,
    PaginatedErrorTrackingFingerprintListApi,
    PaginatedErrorTrackingGroupingRuleListApi,
    PaginatedErrorTrackingIssueFullListApi,
    PaginatedErrorTrackingReleaseListApi,
    PaginatedErrorTrackingStackFrameListApi,
    PaginatedErrorTrackingSuppressionRuleListApi,
    PaginatedErrorTrackingSymbolSetListApi,
    PatchedErrorTrackingAssignmentRuleApi,
    PatchedErrorTrackingExternalReferenceApi,
    PatchedErrorTrackingGroupingRuleApi,
    PatchedErrorTrackingIssueFullApi,
    PatchedErrorTrackingReleaseApi,
    PatchedErrorTrackingSuppressionRuleApi,
    PatchedErrorTrackingSymbolSetApi,
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

export type errorTrackingAssignmentRulesListResponse200 = {
    data: PaginatedErrorTrackingAssignmentRuleListApi
    status: 200
}

export type errorTrackingAssignmentRulesListResponseSuccess = errorTrackingAssignmentRulesListResponse200 & {
    headers: Headers
}
export type errorTrackingAssignmentRulesListResponse = errorTrackingAssignmentRulesListResponseSuccess

export const getErrorTrackingAssignmentRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingAssignmentRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/assignment_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const errorTrackingAssignmentRulesList = async (
    projectId: string,
    params?: ErrorTrackingAssignmentRulesListParams,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesListResponse> => {
    return apiMutator<errorTrackingAssignmentRulesListResponse>(
        getErrorTrackingAssignmentRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingAssignmentRulesCreateResponse201 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 201
}

export type errorTrackingAssignmentRulesCreateResponseSuccess = errorTrackingAssignmentRulesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingAssignmentRulesCreateResponse = errorTrackingAssignmentRulesCreateResponseSuccess

export const getErrorTrackingAssignmentRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const errorTrackingAssignmentRulesCreate = async (
    projectId: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesCreateResponse> => {
    return apiMutator<errorTrackingAssignmentRulesCreateResponse>(getErrorTrackingAssignmentRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingAssignmentRuleApi),
    })
}

export type errorTrackingAssignmentRulesRetrieveResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type errorTrackingAssignmentRulesRetrieveResponseSuccess = errorTrackingAssignmentRulesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingAssignmentRulesRetrieveResponse = errorTrackingAssignmentRulesRetrieveResponseSuccess

export const getErrorTrackingAssignmentRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesRetrieveResponse> => {
    return apiMutator<errorTrackingAssignmentRulesRetrieveResponse>(
        getErrorTrackingAssignmentRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingAssignmentRulesUpdateResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type errorTrackingAssignmentRulesUpdateResponseSuccess = errorTrackingAssignmentRulesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingAssignmentRulesUpdateResponse = errorTrackingAssignmentRulesUpdateResponseSuccess

export const getErrorTrackingAssignmentRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesUpdateResponse> => {
    return apiMutator<errorTrackingAssignmentRulesUpdateResponse>(
        getErrorTrackingAssignmentRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingAssignmentRuleApi),
        }
    )
}

export type errorTrackingAssignmentRulesPartialUpdateResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type errorTrackingAssignmentRulesPartialUpdateResponseSuccess =
    errorTrackingAssignmentRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingAssignmentRulesPartialUpdateResponse = errorTrackingAssignmentRulesPartialUpdateResponseSuccess

export const getErrorTrackingAssignmentRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesPartialUpdateResponse> => {
    return apiMutator<errorTrackingAssignmentRulesPartialUpdateResponse>(
        getErrorTrackingAssignmentRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
        }
    )
}

export type errorTrackingAssignmentRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type errorTrackingAssignmentRulesDestroyResponseSuccess = errorTrackingAssignmentRulesDestroyResponse204 & {
    headers: Headers
}
export type errorTrackingAssignmentRulesDestroyResponse = errorTrackingAssignmentRulesDestroyResponseSuccess

export const getErrorTrackingAssignmentRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const errorTrackingAssignmentRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesDestroyResponse> => {
    return apiMutator<errorTrackingAssignmentRulesDestroyResponse>(
        getErrorTrackingAssignmentRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type errorTrackingAssignmentRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingAssignmentRulesReorderPartialUpdateResponseSuccess =
    errorTrackingAssignmentRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingAssignmentRulesReorderPartialUpdateResponse =
    errorTrackingAssignmentRulesReorderPartialUpdateResponseSuccess

export const getErrorTrackingAssignmentRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/reorder/`
}

export const errorTrackingAssignmentRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<errorTrackingAssignmentRulesReorderPartialUpdateResponse> => {
    return apiMutator<errorTrackingAssignmentRulesReorderPartialUpdateResponse>(
        getErrorTrackingAssignmentRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
        }
    )
}

export type errorTrackingExternalReferencesListResponse200 = {
    data: PaginatedErrorTrackingExternalReferenceListApi
    status: 200
}

export type errorTrackingExternalReferencesListResponseSuccess = errorTrackingExternalReferencesListResponse200 & {
    headers: Headers
}
export type errorTrackingExternalReferencesListResponse = errorTrackingExternalReferencesListResponseSuccess

export const getErrorTrackingExternalReferencesListUrl = (
    projectId: string,
    params?: ErrorTrackingExternalReferencesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/external_references/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/external_references/`
}

export const errorTrackingExternalReferencesList = async (
    projectId: string,
    params?: ErrorTrackingExternalReferencesListParams,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesListResponse> => {
    return apiMutator<errorTrackingExternalReferencesListResponse>(
        getErrorTrackingExternalReferencesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingExternalReferencesCreateResponse201 = {
    data: ErrorTrackingExternalReferenceApi
    status: 201
}

export type errorTrackingExternalReferencesCreateResponseSuccess = errorTrackingExternalReferencesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingExternalReferencesCreateResponse = errorTrackingExternalReferencesCreateResponseSuccess

export const getErrorTrackingExternalReferencesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/`
}

export const errorTrackingExternalReferencesCreate = async (
    projectId: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesCreateResponse> => {
    return apiMutator<errorTrackingExternalReferencesCreateResponse>(
        getErrorTrackingExternalReferencesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export type errorTrackingExternalReferencesRetrieveResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type errorTrackingExternalReferencesRetrieveResponseSuccess =
    errorTrackingExternalReferencesRetrieveResponse200 & {
        headers: Headers
    }
export type errorTrackingExternalReferencesRetrieveResponse = errorTrackingExternalReferencesRetrieveResponseSuccess

export const getErrorTrackingExternalReferencesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesRetrieveResponse> => {
    return apiMutator<errorTrackingExternalReferencesRetrieveResponse>(
        getErrorTrackingExternalReferencesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingExternalReferencesUpdateResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type errorTrackingExternalReferencesUpdateResponseSuccess = errorTrackingExternalReferencesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingExternalReferencesUpdateResponse = errorTrackingExternalReferencesUpdateResponseSuccess

export const getErrorTrackingExternalReferencesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesUpdateResponse> => {
    return apiMutator<errorTrackingExternalReferencesUpdateResponse>(
        getErrorTrackingExternalReferencesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export type errorTrackingExternalReferencesPartialUpdateResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type errorTrackingExternalReferencesPartialUpdateResponseSuccess =
    errorTrackingExternalReferencesPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingExternalReferencesPartialUpdateResponse =
    errorTrackingExternalReferencesPartialUpdateResponseSuccess

export const getErrorTrackingExternalReferencesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingExternalReferenceApi: NonReadonly<PatchedErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesPartialUpdateResponse> => {
    return apiMutator<errorTrackingExternalReferencesPartialUpdateResponse>(
        getErrorTrackingExternalReferencesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingExternalReferenceApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type errorTrackingExternalReferencesDestroyResponse405 = {
    data: void
    status: 405
}
export type errorTrackingExternalReferencesDestroyResponseError = errorTrackingExternalReferencesDestroyResponse405 & {
    headers: Headers
}

export type errorTrackingExternalReferencesDestroyResponse = errorTrackingExternalReferencesDestroyResponseError

export const getErrorTrackingExternalReferencesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const errorTrackingExternalReferencesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingExternalReferencesDestroyResponse> => {
    return apiMutator<errorTrackingExternalReferencesDestroyResponse>(
        getErrorTrackingExternalReferencesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type errorTrackingFingerprintsListResponse200 = {
    data: PaginatedErrorTrackingFingerprintListApi
    status: 200
}

export type errorTrackingFingerprintsListResponseSuccess = errorTrackingFingerprintsListResponse200 & {
    headers: Headers
}
export type errorTrackingFingerprintsListResponse = errorTrackingFingerprintsListResponseSuccess

export const getErrorTrackingFingerprintsListUrl = (
    projectId: string,
    params?: ErrorTrackingFingerprintsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/fingerprints/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/fingerprints/`
}

export const errorTrackingFingerprintsList = async (
    projectId: string,
    params?: ErrorTrackingFingerprintsListParams,
    options?: RequestInit
): Promise<errorTrackingFingerprintsListResponse> => {
    return apiMutator<errorTrackingFingerprintsListResponse>(getErrorTrackingFingerprintsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingFingerprintsRetrieveResponse200 = {
    data: ErrorTrackingFingerprintApi
    status: 200
}

export type errorTrackingFingerprintsRetrieveResponseSuccess = errorTrackingFingerprintsRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingFingerprintsRetrieveResponse = errorTrackingFingerprintsRetrieveResponseSuccess

export const getErrorTrackingFingerprintsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const errorTrackingFingerprintsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingFingerprintsRetrieveResponse> => {
    return apiMutator<errorTrackingFingerprintsRetrieveResponse>(
        getErrorTrackingFingerprintsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type errorTrackingFingerprintsDestroyResponse405 = {
    data: void
    status: 405
}
export type errorTrackingFingerprintsDestroyResponseError = errorTrackingFingerprintsDestroyResponse405 & {
    headers: Headers
}

export type errorTrackingFingerprintsDestroyResponse = errorTrackingFingerprintsDestroyResponseError

export const getErrorTrackingFingerprintsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const errorTrackingFingerprintsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingFingerprintsDestroyResponse> => {
    return apiMutator<errorTrackingFingerprintsDestroyResponse>(getErrorTrackingFingerprintsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingGitProviderFileLinksResolveGithubRetrieveResponse200 = {
    data: void
    status: 200
}

export type errorTrackingGitProviderFileLinksResolveGithubRetrieveResponseSuccess =
    errorTrackingGitProviderFileLinksResolveGithubRetrieveResponse200 & {
        headers: Headers
    }
export type errorTrackingGitProviderFileLinksResolveGithubRetrieveResponse =
    errorTrackingGitProviderFileLinksResolveGithubRetrieveResponseSuccess

export const getErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_github/`
}

export const errorTrackingGitProviderFileLinksResolveGithubRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<errorTrackingGitProviderFileLinksResolveGithubRetrieveResponse> => {
    return apiMutator<errorTrackingGitProviderFileLinksResolveGithubRetrieveResponse>(
        getErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse200 = {
    data: void
    status: 200
}

export type errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponseSuccess =
    errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse200 & {
        headers: Headers
    }
export type errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse =
    errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponseSuccess

export const getErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_gitlab/`
}

export const errorTrackingGitProviderFileLinksResolveGitlabRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse> => {
    return apiMutator<errorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse>(
        getErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingGroupingRulesListResponse200 = {
    data: PaginatedErrorTrackingGroupingRuleListApi
    status: 200
}

export type errorTrackingGroupingRulesListResponseSuccess = errorTrackingGroupingRulesListResponse200 & {
    headers: Headers
}
export type errorTrackingGroupingRulesListResponse = errorTrackingGroupingRulesListResponseSuccess

export const getErrorTrackingGroupingRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingGroupingRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/grouping_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const errorTrackingGroupingRulesList = async (
    projectId: string,
    params?: ErrorTrackingGroupingRulesListParams,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesListResponse> => {
    return apiMutator<errorTrackingGroupingRulesListResponse>(getErrorTrackingGroupingRulesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingGroupingRulesCreateResponse201 = {
    data: ErrorTrackingGroupingRuleApi
    status: 201
}

export type errorTrackingGroupingRulesCreateResponseSuccess = errorTrackingGroupingRulesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingGroupingRulesCreateResponse = errorTrackingGroupingRulesCreateResponseSuccess

export const getErrorTrackingGroupingRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const errorTrackingGroupingRulesCreate = async (
    projectId: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesCreateResponse> => {
    return apiMutator<errorTrackingGroupingRulesCreateResponse>(getErrorTrackingGroupingRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export type errorTrackingGroupingRulesRetrieveResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type errorTrackingGroupingRulesRetrieveResponseSuccess = errorTrackingGroupingRulesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingGroupingRulesRetrieveResponse = errorTrackingGroupingRulesRetrieveResponseSuccess

export const getErrorTrackingGroupingRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesRetrieveResponse> => {
    return apiMutator<errorTrackingGroupingRulesRetrieveResponse>(
        getErrorTrackingGroupingRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingGroupingRulesUpdateResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type errorTrackingGroupingRulesUpdateResponseSuccess = errorTrackingGroupingRulesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingGroupingRulesUpdateResponse = errorTrackingGroupingRulesUpdateResponseSuccess

export const getErrorTrackingGroupingRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesUpdateResponse> => {
    return apiMutator<errorTrackingGroupingRulesUpdateResponse>(getErrorTrackingGroupingRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingGroupingRuleApi),
    })
}

export type errorTrackingGroupingRulesPartialUpdateResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type errorTrackingGroupingRulesPartialUpdateResponseSuccess =
    errorTrackingGroupingRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingGroupingRulesPartialUpdateResponse = errorTrackingGroupingRulesPartialUpdateResponseSuccess

export const getErrorTrackingGroupingRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesPartialUpdateResponse> => {
    return apiMutator<errorTrackingGroupingRulesPartialUpdateResponse>(
        getErrorTrackingGroupingRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
        }
    )
}

export type errorTrackingGroupingRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type errorTrackingGroupingRulesDestroyResponseSuccess = errorTrackingGroupingRulesDestroyResponse204 & {
    headers: Headers
}
export type errorTrackingGroupingRulesDestroyResponse = errorTrackingGroupingRulesDestroyResponseSuccess

export const getErrorTrackingGroupingRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const errorTrackingGroupingRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesDestroyResponse> => {
    return apiMutator<errorTrackingGroupingRulesDestroyResponse>(
        getErrorTrackingGroupingRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type errorTrackingGroupingRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingGroupingRulesReorderPartialUpdateResponseSuccess =
    errorTrackingGroupingRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingGroupingRulesReorderPartialUpdateResponse =
    errorTrackingGroupingRulesReorderPartialUpdateResponseSuccess

export const getErrorTrackingGroupingRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/reorder/`
}

export const errorTrackingGroupingRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<errorTrackingGroupingRulesReorderPartialUpdateResponse> => {
    return apiMutator<errorTrackingGroupingRulesReorderPartialUpdateResponse>(
        getErrorTrackingGroupingRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
        }
    )
}

export type errorTrackingIssuesListResponse200 = {
    data: PaginatedErrorTrackingIssueFullListApi
    status: 200
}

export type errorTrackingIssuesListResponseSuccess = errorTrackingIssuesListResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesListResponse = errorTrackingIssuesListResponseSuccess

export const getErrorTrackingIssuesListUrl = (projectId: string, params?: ErrorTrackingIssuesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/issues/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/issues/`
}

export const errorTrackingIssuesList = async (
    projectId: string,
    params?: ErrorTrackingIssuesListParams,
    options?: RequestInit
): Promise<errorTrackingIssuesListResponse> => {
    return apiMutator<errorTrackingIssuesListResponse>(getErrorTrackingIssuesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingIssuesCreateResponse201 = {
    data: ErrorTrackingIssueFullApi
    status: 201
}

export type errorTrackingIssuesCreateResponseSuccess = errorTrackingIssuesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingIssuesCreateResponse = errorTrackingIssuesCreateResponseSuccess

export const getErrorTrackingIssuesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/`
}

export const errorTrackingIssuesCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesCreateResponse> => {
    return apiMutator<errorTrackingIssuesCreateResponse>(getErrorTrackingIssuesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesRetrieveResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type errorTrackingIssuesRetrieveResponseSuccess = errorTrackingIssuesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesRetrieveResponse = errorTrackingIssuesRetrieveResponseSuccess

export const getErrorTrackingIssuesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingIssuesRetrieveResponse> => {
    return apiMutator<errorTrackingIssuesRetrieveResponse>(getErrorTrackingIssuesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingIssuesUpdateResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type errorTrackingIssuesUpdateResponseSuccess = errorTrackingIssuesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesUpdateResponse = errorTrackingIssuesUpdateResponseSuccess

export const getErrorTrackingIssuesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesUpdateResponse> => {
    return apiMutator<errorTrackingIssuesUpdateResponse>(getErrorTrackingIssuesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesPartialUpdateResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type errorTrackingIssuesPartialUpdateResponseSuccess = errorTrackingIssuesPartialUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesPartialUpdateResponse = errorTrackingIssuesPartialUpdateResponseSuccess

export const getErrorTrackingIssuesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesPartialUpdateResponse> => {
    return apiMutator<errorTrackingIssuesPartialUpdateResponse>(getErrorTrackingIssuesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedErrorTrackingIssueFullApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type errorTrackingIssuesDestroyResponse405 = {
    data: void
    status: 405
}
export type errorTrackingIssuesDestroyResponseError = errorTrackingIssuesDestroyResponse405 & {
    headers: Headers
}

export type errorTrackingIssuesDestroyResponse = errorTrackingIssuesDestroyResponseError

export const getErrorTrackingIssuesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const errorTrackingIssuesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingIssuesDestroyResponse> => {
    return apiMutator<errorTrackingIssuesDestroyResponse>(getErrorTrackingIssuesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingIssuesActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesActivityRetrieve2ResponseSuccess = errorTrackingIssuesActivityRetrieve2Response200 & {
    headers: Headers
}
export type errorTrackingIssuesActivityRetrieve2Response = errorTrackingIssuesActivityRetrieve2ResponseSuccess

export const getErrorTrackingIssuesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/activity/`
}

export const errorTrackingIssuesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingIssuesActivityRetrieve2Response> => {
    return apiMutator<errorTrackingIssuesActivityRetrieve2Response>(
        getErrorTrackingIssuesActivityRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingIssuesAssignPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesAssignPartialUpdateResponseSuccess =
    errorTrackingIssuesAssignPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingIssuesAssignPartialUpdateResponse = errorTrackingIssuesAssignPartialUpdateResponseSuccess

export const getErrorTrackingIssuesAssignPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/assign/`
}

export const errorTrackingIssuesAssignPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesAssignPartialUpdateResponse> => {
    return apiMutator<errorTrackingIssuesAssignPartialUpdateResponse>(
        getErrorTrackingIssuesAssignPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingIssueFullApi),
        }
    )
}

export type errorTrackingIssuesCohortUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesCohortUpdateResponseSuccess = errorTrackingIssuesCohortUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesCohortUpdateResponse = errorTrackingIssuesCohortUpdateResponseSuccess

export const getErrorTrackingIssuesCohortUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/cohort/`
}

export const errorTrackingIssuesCohortUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesCohortUpdateResponse> => {
    return apiMutator<errorTrackingIssuesCohortUpdateResponse>(getErrorTrackingIssuesCohortUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesMergeCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesMergeCreateResponseSuccess = errorTrackingIssuesMergeCreateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesMergeCreateResponse = errorTrackingIssuesMergeCreateResponseSuccess

export const getErrorTrackingIssuesMergeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/merge/`
}

export const errorTrackingIssuesMergeCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesMergeCreateResponse> => {
    return apiMutator<errorTrackingIssuesMergeCreateResponse>(getErrorTrackingIssuesMergeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesSplitCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesSplitCreateResponseSuccess = errorTrackingIssuesSplitCreateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesSplitCreateResponse = errorTrackingIssuesSplitCreateResponseSuccess

export const getErrorTrackingIssuesSplitCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/split/`
}

export const errorTrackingIssuesSplitCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesSplitCreateResponse> => {
    return apiMutator<errorTrackingIssuesSplitCreateResponse>(getErrorTrackingIssuesSplitCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesActivityRetrieveResponseSuccess = errorTrackingIssuesActivityRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesActivityRetrieveResponse = errorTrackingIssuesActivityRetrieveResponseSuccess

export const getErrorTrackingIssuesActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/activity/`
}

export const errorTrackingIssuesActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<errorTrackingIssuesActivityRetrieveResponse> => {
    return apiMutator<errorTrackingIssuesActivityRetrieveResponse>(
        getErrorTrackingIssuesActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingIssuesBulkCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesBulkCreateResponseSuccess = errorTrackingIssuesBulkCreateResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesBulkCreateResponse = errorTrackingIssuesBulkCreateResponseSuccess

export const getErrorTrackingIssuesBulkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/bulk/`
}

export const errorTrackingIssuesBulkCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<errorTrackingIssuesBulkCreateResponse> => {
    return apiMutator<errorTrackingIssuesBulkCreateResponse>(getErrorTrackingIssuesBulkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingIssueFullApi),
    })
}

export type errorTrackingIssuesValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type errorTrackingIssuesValuesRetrieveResponseSuccess = errorTrackingIssuesValuesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingIssuesValuesRetrieveResponse = errorTrackingIssuesValuesRetrieveResponseSuccess

export const getErrorTrackingIssuesValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/values/`
}

export const errorTrackingIssuesValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<errorTrackingIssuesValuesRetrieveResponse> => {
    return apiMutator<errorTrackingIssuesValuesRetrieveResponse>(getErrorTrackingIssuesValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingReleasesListResponse200 = {
    data: PaginatedErrorTrackingReleaseListApi
    status: 200
}

export type errorTrackingReleasesListResponseSuccess = errorTrackingReleasesListResponse200 & {
    headers: Headers
}
export type errorTrackingReleasesListResponse = errorTrackingReleasesListResponseSuccess

export const getErrorTrackingReleasesListUrl = (projectId: string, params?: ErrorTrackingReleasesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesList = async (
    projectId: string,
    params?: ErrorTrackingReleasesListParams,
    options?: RequestInit
): Promise<errorTrackingReleasesListResponse> => {
    return apiMutator<errorTrackingReleasesListResponse>(getErrorTrackingReleasesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingReleasesCreateResponse201 = {
    data: ErrorTrackingReleaseApi
    status: 201
}

export type errorTrackingReleasesCreateResponseSuccess = errorTrackingReleasesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingReleasesCreateResponse = errorTrackingReleasesCreateResponseSuccess

export const getErrorTrackingReleasesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesCreate = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesCreateResponse> => {
    return apiMutator<errorTrackingReleasesCreateResponse>(getErrorTrackingReleasesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export type errorTrackingReleasesRetrieveResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesRetrieveResponseSuccess = errorTrackingReleasesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingReleasesRetrieveResponse = errorTrackingReleasesRetrieveResponseSuccess

export const getErrorTrackingReleasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingReleasesRetrieveResponse> => {
    return apiMutator<errorTrackingReleasesRetrieveResponse>(getErrorTrackingReleasesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingReleasesUpdateResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesUpdateResponseSuccess = errorTrackingReleasesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingReleasesUpdateResponse = errorTrackingReleasesUpdateResponseSuccess

export const getErrorTrackingReleasesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesUpdateResponse> => {
    return apiMutator<errorTrackingReleasesUpdateResponse>(getErrorTrackingReleasesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export type errorTrackingReleasesPartialUpdateResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesPartialUpdateResponseSuccess = errorTrackingReleasesPartialUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingReleasesPartialUpdateResponse = errorTrackingReleasesPartialUpdateResponseSuccess

export const getErrorTrackingReleasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesPartialUpdateResponse> => {
    return apiMutator<errorTrackingReleasesPartialUpdateResponse>(
        getErrorTrackingReleasesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingReleaseApi),
        }
    )
}

export type errorTrackingReleasesDestroyResponse204 = {
    data: void
    status: 204
}

export type errorTrackingReleasesDestroyResponseSuccess = errorTrackingReleasesDestroyResponse204 & {
    headers: Headers
}
export type errorTrackingReleasesDestroyResponse = errorTrackingReleasesDestroyResponseSuccess

export const getErrorTrackingReleasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingReleasesDestroyResponse> => {
    return apiMutator<errorTrackingReleasesDestroyResponse>(getErrorTrackingReleasesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingReleasesHashRetrieveResponse200 = {
    data: void
    status: 200
}

export type errorTrackingReleasesHashRetrieveResponseSuccess = errorTrackingReleasesHashRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingReleasesHashRetrieveResponse = errorTrackingReleasesHashRetrieveResponseSuccess

export const getErrorTrackingReleasesHashRetrieveUrl = (projectId: string, hashId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const errorTrackingReleasesHashRetrieve = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<errorTrackingReleasesHashRetrieveResponse> => {
    return apiMutator<errorTrackingReleasesHashRetrieveResponse>(
        getErrorTrackingReleasesHashRetrieveUrl(projectId, hashId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingStackFramesListResponse200 = {
    data: PaginatedErrorTrackingStackFrameListApi
    status: 200
}

export type errorTrackingStackFramesListResponseSuccess = errorTrackingStackFramesListResponse200 & {
    headers: Headers
}
export type errorTrackingStackFramesListResponse = errorTrackingStackFramesListResponseSuccess

export const getErrorTrackingStackFramesListUrl = (projectId: string, params?: ErrorTrackingStackFramesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/stack_frames/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/stack_frames/`
}

export const errorTrackingStackFramesList = async (
    projectId: string,
    params?: ErrorTrackingStackFramesListParams,
    options?: RequestInit
): Promise<errorTrackingStackFramesListResponse> => {
    return apiMutator<errorTrackingStackFramesListResponse>(getErrorTrackingStackFramesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingStackFramesRetrieveResponse200 = {
    data: ErrorTrackingStackFrameApi
    status: 200
}

export type errorTrackingStackFramesRetrieveResponseSuccess = errorTrackingStackFramesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingStackFramesRetrieveResponse = errorTrackingStackFramesRetrieveResponseSuccess

export const getErrorTrackingStackFramesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const errorTrackingStackFramesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingStackFramesRetrieveResponse> => {
    return apiMutator<errorTrackingStackFramesRetrieveResponse>(getErrorTrackingStackFramesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type errorTrackingStackFramesDestroyResponse405 = {
    data: void
    status: 405
}
export type errorTrackingStackFramesDestroyResponseError = errorTrackingStackFramesDestroyResponse405 & {
    headers: Headers
}

export type errorTrackingStackFramesDestroyResponse = errorTrackingStackFramesDestroyResponseError

export const getErrorTrackingStackFramesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const errorTrackingStackFramesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingStackFramesDestroyResponse> => {
    return apiMutator<errorTrackingStackFramesDestroyResponse>(getErrorTrackingStackFramesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingStackFramesBatchGetCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingStackFramesBatchGetCreateResponseSuccess =
    errorTrackingStackFramesBatchGetCreateResponse200 & {
        headers: Headers
    }
export type errorTrackingStackFramesBatchGetCreateResponse = errorTrackingStackFramesBatchGetCreateResponseSuccess

export const getErrorTrackingStackFramesBatchGetCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/batch_get/`
}

export const errorTrackingStackFramesBatchGetCreate = async (
    projectId: string,
    errorTrackingStackFrameApi: NonReadonly<ErrorTrackingStackFrameApi>,
    options?: RequestInit
): Promise<errorTrackingStackFramesBatchGetCreateResponse> => {
    return apiMutator<errorTrackingStackFramesBatchGetCreateResponse>(
        getErrorTrackingStackFramesBatchGetCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingStackFrameApi),
        }
    )
}

export type errorTrackingSuppressionRulesListResponse200 = {
    data: PaginatedErrorTrackingSuppressionRuleListApi
    status: 200
}

export type errorTrackingSuppressionRulesListResponseSuccess = errorTrackingSuppressionRulesListResponse200 & {
    headers: Headers
}
export type errorTrackingSuppressionRulesListResponse = errorTrackingSuppressionRulesListResponseSuccess

export const getErrorTrackingSuppressionRulesListUrl = (
    projectId: string,
    params?: ErrorTrackingSuppressionRulesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/suppression_rules/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const errorTrackingSuppressionRulesList = async (
    projectId: string,
    params?: ErrorTrackingSuppressionRulesListParams,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesListResponse> => {
    return apiMutator<errorTrackingSuppressionRulesListResponse>(
        getErrorTrackingSuppressionRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingSuppressionRulesCreateResponse201 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 201
}

export type errorTrackingSuppressionRulesCreateResponseSuccess = errorTrackingSuppressionRulesCreateResponse201 & {
    headers: Headers
}
export type errorTrackingSuppressionRulesCreateResponse = errorTrackingSuppressionRulesCreateResponseSuccess

export const getErrorTrackingSuppressionRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const errorTrackingSuppressionRulesCreate = async (
    projectId: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesCreateResponse> => {
    return apiMutator<errorTrackingSuppressionRulesCreateResponse>(
        getErrorTrackingSuppressionRulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export type errorTrackingSuppressionRulesRetrieveResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type errorTrackingSuppressionRulesRetrieveResponseSuccess = errorTrackingSuppressionRulesRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingSuppressionRulesRetrieveResponse = errorTrackingSuppressionRulesRetrieveResponseSuccess

export const getErrorTrackingSuppressionRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesRetrieveResponse> => {
    return apiMutator<errorTrackingSuppressionRulesRetrieveResponse>(
        getErrorTrackingSuppressionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingSuppressionRulesUpdateResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type errorTrackingSuppressionRulesUpdateResponseSuccess = errorTrackingSuppressionRulesUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingSuppressionRulesUpdateResponse = errorTrackingSuppressionRulesUpdateResponseSuccess

export const getErrorTrackingSuppressionRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesUpdateResponse> => {
    return apiMutator<errorTrackingSuppressionRulesUpdateResponse>(
        getErrorTrackingSuppressionRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export type errorTrackingSuppressionRulesPartialUpdateResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type errorTrackingSuppressionRulesPartialUpdateResponseSuccess =
    errorTrackingSuppressionRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingSuppressionRulesPartialUpdateResponse =
    errorTrackingSuppressionRulesPartialUpdateResponseSuccess

export const getErrorTrackingSuppressionRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesPartialUpdateResponse> => {
    return apiMutator<errorTrackingSuppressionRulesPartialUpdateResponse>(
        getErrorTrackingSuppressionRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export type errorTrackingSuppressionRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type errorTrackingSuppressionRulesDestroyResponseSuccess = errorTrackingSuppressionRulesDestroyResponse204 & {
    headers: Headers
}
export type errorTrackingSuppressionRulesDestroyResponse = errorTrackingSuppressionRulesDestroyResponseSuccess

export const getErrorTrackingSuppressionRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const errorTrackingSuppressionRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesDestroyResponse> => {
    return apiMutator<errorTrackingSuppressionRulesDestroyResponse>(
        getErrorTrackingSuppressionRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type errorTrackingSuppressionRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingSuppressionRulesReorderPartialUpdateResponseSuccess =
    errorTrackingSuppressionRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingSuppressionRulesReorderPartialUpdateResponse =
    errorTrackingSuppressionRulesReorderPartialUpdateResponseSuccess

export const getErrorTrackingSuppressionRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/reorder/`
}

export const errorTrackingSuppressionRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<errorTrackingSuppressionRulesReorderPartialUpdateResponse> => {
    return apiMutator<errorTrackingSuppressionRulesReorderPartialUpdateResponse>(
        getErrorTrackingSuppressionRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export type errorTrackingSymbolSetsListResponse200 = {
    data: PaginatedErrorTrackingSymbolSetListApi
    status: 200
}

export type errorTrackingSymbolSetsListResponseSuccess = errorTrackingSymbolSetsListResponse200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsListResponse = errorTrackingSymbolSetsListResponseSuccess

export const getErrorTrackingSymbolSetsListUrl = (projectId: string, params?: ErrorTrackingSymbolSetsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/error_tracking/symbol_sets/?${stringifiedParams}`
        : `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsList = async (
    projectId: string,
    params?: ErrorTrackingSymbolSetsListParams,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsListResponse> => {
    return apiMutator<errorTrackingSymbolSetsListResponse>(getErrorTrackingSymbolSetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingSymbolSetsCreateResponse201 = {
    data: ErrorTrackingSymbolSetApi
    status: 201
}

export type errorTrackingSymbolSetsCreateResponseSuccess = errorTrackingSymbolSetsCreateResponse201 & {
    headers: Headers
}
export type errorTrackingSymbolSetsCreateResponse = errorTrackingSymbolSetsCreateResponseSuccess

export const getErrorTrackingSymbolSetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsCreate = async (
    projectId: string,
    errorTrackingSymbolSetsCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsCreateResponse> => {
    return apiMutator<errorTrackingSymbolSetsCreateResponse>(getErrorTrackingSymbolSetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsCreateBody),
    })
}

export type errorTrackingSymbolSetsRetrieveResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsRetrieveResponseSuccess = errorTrackingSymbolSetsRetrieveResponse200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsRetrieveResponse = errorTrackingSymbolSetsRetrieveResponseSuccess

export const getErrorTrackingSymbolSetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsRetrieveResponse> => {
    return apiMutator<errorTrackingSymbolSetsRetrieveResponse>(getErrorTrackingSymbolSetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingSymbolSetsUpdateResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsUpdateResponseSuccess = errorTrackingSymbolSetsUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsUpdateResponse = errorTrackingSymbolSetsUpdateResponseSuccess

export const getErrorTrackingSymbolSetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsUpdateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsUpdateResponse> => {
    return apiMutator<errorTrackingSymbolSetsUpdateResponse>(getErrorTrackingSymbolSetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: JSON.stringify(errorTrackingSymbolSetsUpdateBody),
    })
}

export type errorTrackingSymbolSetsPartialUpdateResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsPartialUpdateResponseSuccess = errorTrackingSymbolSetsPartialUpdateResponse200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsPartialUpdateResponse = errorTrackingSymbolSetsPartialUpdateResponseSuccess

export const getErrorTrackingSymbolSetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsPartialUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsPartialUpdateBody: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsPartialUpdateResponse> => {
    return apiMutator<errorTrackingSymbolSetsPartialUpdateResponse>(
        getErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: JSON.stringify(errorTrackingSymbolSetsPartialUpdateBody),
        }
    )
}

export type errorTrackingSymbolSetsDestroyResponse204 = {
    data: void
    status: 204
}

export type errorTrackingSymbolSetsDestroyResponseSuccess = errorTrackingSymbolSetsDestroyResponse204 & {
    headers: Headers
}
export type errorTrackingSymbolSetsDestroyResponse = errorTrackingSymbolSetsDestroyResponseSuccess

export const getErrorTrackingSymbolSetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsDestroyResponse> => {
    return apiMutator<errorTrackingSymbolSetsDestroyResponse>(getErrorTrackingSymbolSetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingSymbolSetsFinishUploadUpdateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsFinishUploadUpdateResponseSuccess =
    errorTrackingSymbolSetsFinishUploadUpdateResponse200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsFinishUploadUpdateResponse = errorTrackingSymbolSetsFinishUploadUpdateResponseSuccess

export const getErrorTrackingSymbolSetsFinishUploadUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const errorTrackingSymbolSetsFinishUploadUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsFinishUploadUpdateResponse> => {
    return apiMutator<errorTrackingSymbolSetsFinishUploadUpdateResponse>(
        getErrorTrackingSymbolSetsFinishUploadUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsBulkFinishUploadCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsBulkFinishUploadCreateResponseSuccess =
    errorTrackingSymbolSetsBulkFinishUploadCreateResponse200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsBulkFinishUploadCreateResponse =
    errorTrackingSymbolSetsBulkFinishUploadCreateResponseSuccess

export const getErrorTrackingSymbolSetsBulkFinishUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const errorTrackingSymbolSetsBulkFinishUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsBulkFinishUploadCreateResponse> => {
    return apiMutator<errorTrackingSymbolSetsBulkFinishUploadCreateResponse>(
        getErrorTrackingSymbolSetsBulkFinishUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsBulkStartUploadCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsBulkStartUploadCreateResponseSuccess =
    errorTrackingSymbolSetsBulkStartUploadCreateResponse200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsBulkStartUploadCreateResponse =
    errorTrackingSymbolSetsBulkStartUploadCreateResponseSuccess

export const getErrorTrackingSymbolSetsBulkStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const errorTrackingSymbolSetsBulkStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsBulkStartUploadCreateResponse> => {
    return apiMutator<errorTrackingSymbolSetsBulkStartUploadCreateResponse>(
        getErrorTrackingSymbolSetsBulkStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsStartUploadCreateResponse200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsStartUploadCreateResponseSuccess =
    errorTrackingSymbolSetsStartUploadCreateResponse200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsStartUploadCreateResponse = errorTrackingSymbolSetsStartUploadCreateResponseSuccess

export const getErrorTrackingSymbolSetsStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const errorTrackingSymbolSetsStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetsStartUploadCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsStartUploadCreateResponse> => {
    return apiMutator<errorTrackingSymbolSetsStartUploadCreateResponse>(
        getErrorTrackingSymbolSetsStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: JSON.stringify(errorTrackingSymbolSetsStartUploadCreateBody),
        }
    )
}

export type errorTrackingReleasesList2Response200 = {
    data: PaginatedErrorTrackingReleaseListApi
    status: 200
}

export type errorTrackingReleasesList2ResponseSuccess = errorTrackingReleasesList2Response200 & {
    headers: Headers
}
export type errorTrackingReleasesList2Response = errorTrackingReleasesList2ResponseSuccess

export const getErrorTrackingReleasesList2Url = (projectId: string, params?: ErrorTrackingReleasesList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesList2 = async (
    projectId: string,
    params?: ErrorTrackingReleasesList2Params,
    options?: RequestInit
): Promise<errorTrackingReleasesList2Response> => {
    return apiMutator<errorTrackingReleasesList2Response>(getErrorTrackingReleasesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingReleasesCreate2Response201 = {
    data: ErrorTrackingReleaseApi
    status: 201
}

export type errorTrackingReleasesCreate2ResponseSuccess = errorTrackingReleasesCreate2Response201 & {
    headers: Headers
}
export type errorTrackingReleasesCreate2Response = errorTrackingReleasesCreate2ResponseSuccess

export const getErrorTrackingReleasesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/`
}

export const errorTrackingReleasesCreate2 = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesCreate2Response> => {
    return apiMutator<errorTrackingReleasesCreate2Response>(getErrorTrackingReleasesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export type errorTrackingReleasesRetrieve2Response200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesRetrieve2ResponseSuccess = errorTrackingReleasesRetrieve2Response200 & {
    headers: Headers
}
export type errorTrackingReleasesRetrieve2Response = errorTrackingReleasesRetrieve2ResponseSuccess

export const getErrorTrackingReleasesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingReleasesRetrieve2Response> => {
    return apiMutator<errorTrackingReleasesRetrieve2Response>(getErrorTrackingReleasesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingReleasesUpdate2Response200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesUpdate2ResponseSuccess = errorTrackingReleasesUpdate2Response200 & {
    headers: Headers
}
export type errorTrackingReleasesUpdate2Response = errorTrackingReleasesUpdate2ResponseSuccess

export const getErrorTrackingReleasesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesUpdate2Response> => {
    return apiMutator<errorTrackingReleasesUpdate2Response>(getErrorTrackingReleasesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(errorTrackingReleaseApi),
    })
}

export type errorTrackingReleasesPartialUpdate2Response200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type errorTrackingReleasesPartialUpdate2ResponseSuccess = errorTrackingReleasesPartialUpdate2Response200 & {
    headers: Headers
}
export type errorTrackingReleasesPartialUpdate2Response = errorTrackingReleasesPartialUpdate2ResponseSuccess

export const getErrorTrackingReleasesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<errorTrackingReleasesPartialUpdate2Response> => {
    return apiMutator<errorTrackingReleasesPartialUpdate2Response>(
        getErrorTrackingReleasesPartialUpdate2Url(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingReleaseApi),
        }
    )
}

export type errorTrackingReleasesDestroy2Response204 = {
    data: void
    status: 204
}

export type errorTrackingReleasesDestroy2ResponseSuccess = errorTrackingReleasesDestroy2Response204 & {
    headers: Headers
}
export type errorTrackingReleasesDestroy2Response = errorTrackingReleasesDestroy2ResponseSuccess

export const getErrorTrackingReleasesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
}

export const errorTrackingReleasesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingReleasesDestroy2Response> => {
    return apiMutator<errorTrackingReleasesDestroy2Response>(getErrorTrackingReleasesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingReleasesHashRetrieve2Response200 = {
    data: void
    status: 200
}

export type errorTrackingReleasesHashRetrieve2ResponseSuccess = errorTrackingReleasesHashRetrieve2Response200 & {
    headers: Headers
}
export type errorTrackingReleasesHashRetrieve2Response = errorTrackingReleasesHashRetrieve2ResponseSuccess

export const getErrorTrackingReleasesHashRetrieve2Url = (projectId: string, hashId: string) => {
    return `/api/projects/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const errorTrackingReleasesHashRetrieve2 = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<errorTrackingReleasesHashRetrieve2Response> => {
    return apiMutator<errorTrackingReleasesHashRetrieve2Response>(
        getErrorTrackingReleasesHashRetrieve2Url(projectId, hashId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type errorTrackingSymbolSetsList2Response200 = {
    data: PaginatedErrorTrackingSymbolSetListApi
    status: 200
}

export type errorTrackingSymbolSetsList2ResponseSuccess = errorTrackingSymbolSetsList2Response200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsList2Response = errorTrackingSymbolSetsList2ResponseSuccess

export const getErrorTrackingSymbolSetsList2Url = (projectId: string, params?: ErrorTrackingSymbolSetsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/error_tracking/symbol_sets/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsList2 = async (
    projectId: string,
    params?: ErrorTrackingSymbolSetsList2Params,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsList2Response> => {
    return apiMutator<errorTrackingSymbolSetsList2Response>(getErrorTrackingSymbolSetsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingSymbolSetsCreate2Response201 = {
    data: ErrorTrackingSymbolSetApi
    status: 201
}

export type errorTrackingSymbolSetsCreate2ResponseSuccess = errorTrackingSymbolSetsCreate2Response201 & {
    headers: Headers
}
export type errorTrackingSymbolSetsCreate2Response = errorTrackingSymbolSetsCreate2ResponseSuccess

export const getErrorTrackingSymbolSetsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/`
}

export const errorTrackingSymbolSetsCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetsCreate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsCreate2Response> => {
    return apiMutator<errorTrackingSymbolSetsCreate2Response>(getErrorTrackingSymbolSetsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(errorTrackingSymbolSetsCreate2Body),
    })
}

export type errorTrackingSymbolSetsRetrieve2Response200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsRetrieve2ResponseSuccess = errorTrackingSymbolSetsRetrieve2Response200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsRetrieve2Response = errorTrackingSymbolSetsRetrieve2ResponseSuccess

export const getErrorTrackingSymbolSetsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsRetrieve2Response> => {
    return apiMutator<errorTrackingSymbolSetsRetrieve2Response>(getErrorTrackingSymbolSetsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type errorTrackingSymbolSetsUpdate2Response200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsUpdate2ResponseSuccess = errorTrackingSymbolSetsUpdate2Response200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsUpdate2Response = errorTrackingSymbolSetsUpdate2ResponseSuccess

export const getErrorTrackingSymbolSetsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsUpdate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsUpdate2Response> => {
    return apiMutator<errorTrackingSymbolSetsUpdate2Response>(getErrorTrackingSymbolSetsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        body: JSON.stringify(errorTrackingSymbolSetsUpdate2Body),
    })
}

export type errorTrackingSymbolSetsPartialUpdate2Response200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type errorTrackingSymbolSetsPartialUpdate2ResponseSuccess = errorTrackingSymbolSetsPartialUpdate2Response200 & {
    headers: Headers
}
export type errorTrackingSymbolSetsPartialUpdate2Response = errorTrackingSymbolSetsPartialUpdate2ResponseSuccess

export const getErrorTrackingSymbolSetsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsPartialUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetsPartialUpdate2Body: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsPartialUpdate2Response> => {
    return apiMutator<errorTrackingSymbolSetsPartialUpdate2Response>(
        getErrorTrackingSymbolSetsPartialUpdate2Url(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: JSON.stringify(errorTrackingSymbolSetsPartialUpdate2Body),
        }
    )
}

export type errorTrackingSymbolSetsDestroy2Response204 = {
    data: void
    status: 204
}

export type errorTrackingSymbolSetsDestroy2ResponseSuccess = errorTrackingSymbolSetsDestroy2Response204 & {
    headers: Headers
}
export type errorTrackingSymbolSetsDestroy2Response = errorTrackingSymbolSetsDestroy2ResponseSuccess

export const getErrorTrackingSymbolSetsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const errorTrackingSymbolSetsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsDestroy2Response> => {
    return apiMutator<errorTrackingSymbolSetsDestroy2Response>(getErrorTrackingSymbolSetsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type errorTrackingSymbolSetsFinishUploadUpdate2Response200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsFinishUploadUpdate2ResponseSuccess =
    errorTrackingSymbolSetsFinishUploadUpdate2Response200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsFinishUploadUpdate2Response =
    errorTrackingSymbolSetsFinishUploadUpdate2ResponseSuccess

export const getErrorTrackingSymbolSetsFinishUploadUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const errorTrackingSymbolSetsFinishUploadUpdate2 = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsFinishUploadUpdate2Response> => {
    return apiMutator<errorTrackingSymbolSetsFinishUploadUpdate2Response>(
        getErrorTrackingSymbolSetsFinishUploadUpdate2Url(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsBulkFinishUploadCreate2Response200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsBulkFinishUploadCreate2ResponseSuccess =
    errorTrackingSymbolSetsBulkFinishUploadCreate2Response200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsBulkFinishUploadCreate2Response =
    errorTrackingSymbolSetsBulkFinishUploadCreate2ResponseSuccess

export const getErrorTrackingSymbolSetsBulkFinishUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const errorTrackingSymbolSetsBulkFinishUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsBulkFinishUploadCreate2Response> => {
    return apiMutator<errorTrackingSymbolSetsBulkFinishUploadCreate2Response>(
        getErrorTrackingSymbolSetsBulkFinishUploadCreate2Url(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsBulkStartUploadCreate2Response200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsBulkStartUploadCreate2ResponseSuccess =
    errorTrackingSymbolSetsBulkStartUploadCreate2Response200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsBulkStartUploadCreate2Response =
    errorTrackingSymbolSetsBulkStartUploadCreate2ResponseSuccess

export const getErrorTrackingSymbolSetsBulkStartUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const errorTrackingSymbolSetsBulkStartUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsBulkStartUploadCreate2Response> => {
    return apiMutator<errorTrackingSymbolSetsBulkStartUploadCreate2Response>(
        getErrorTrackingSymbolSetsBulkStartUploadCreate2Url(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type errorTrackingSymbolSetsStartUploadCreate2Response200 = {
    data: void
    status: 200
}

export type errorTrackingSymbolSetsStartUploadCreate2ResponseSuccess =
    errorTrackingSymbolSetsStartUploadCreate2Response200 & {
        headers: Headers
    }
export type errorTrackingSymbolSetsStartUploadCreate2Response = errorTrackingSymbolSetsStartUploadCreate2ResponseSuccess

export const getErrorTrackingSymbolSetsStartUploadCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const errorTrackingSymbolSetsStartUploadCreate2 = async (
    projectId: string,
    errorTrackingSymbolSetsStartUploadCreate2Body: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsStartUploadCreate2Response> => {
    return apiMutator<errorTrackingSymbolSetsStartUploadCreate2Response>(
        getErrorTrackingSymbolSetsStartUploadCreate2Url(projectId),
        {
            ...options,
            method: 'POST',
            body: JSON.stringify(errorTrackingSymbolSetsStartUploadCreate2Body),
        }
    )
}
