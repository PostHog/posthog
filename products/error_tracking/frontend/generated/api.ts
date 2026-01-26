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
    EnvironmentsErrorTrackingAssignmentRulesListParams,
    EnvironmentsErrorTrackingExternalReferencesListParams,
    EnvironmentsErrorTrackingFingerprintsListParams,
    EnvironmentsErrorTrackingGroupingRulesListParams,
    EnvironmentsErrorTrackingIssuesListParams,
    EnvironmentsErrorTrackingReleasesListParams,
    EnvironmentsErrorTrackingStackFramesListParams,
    EnvironmentsErrorTrackingSuppressionRulesListParams,
    EnvironmentsErrorTrackingSymbolSetsListParams,
    ErrorTrackingAssignmentRuleApi,
    ErrorTrackingExternalReferenceApi,
    ErrorTrackingFingerprintApi,
    ErrorTrackingGroupingRuleApi,
    ErrorTrackingIssueFullApi,
    ErrorTrackingReleaseApi,
    ErrorTrackingReleasesListParams,
    ErrorTrackingStackFrameApi,
    ErrorTrackingSuppressionRuleApi,
    ErrorTrackingSymbolSetApi,
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

export type environmentsErrorTrackingAssignmentRulesListResponse200 = {
    data: PaginatedErrorTrackingAssignmentRuleListApi
    status: 200
}

export type environmentsErrorTrackingAssignmentRulesListResponseSuccess =
    environmentsErrorTrackingAssignmentRulesListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesListResponse =
    environmentsErrorTrackingAssignmentRulesListResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingAssignmentRulesListParams
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

export const environmentsErrorTrackingAssignmentRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingAssignmentRulesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesListResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesListResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesCreateResponse201 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 201
}

export type environmentsErrorTrackingAssignmentRulesCreateResponseSuccess =
    environmentsErrorTrackingAssignmentRulesCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesCreateResponse =
    environmentsErrorTrackingAssignmentRulesCreateResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/`
}

export const environmentsErrorTrackingAssignmentRulesCreate = async (
    projectId: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesCreateResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingAssignmentRuleApi),
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesRetrieveResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type environmentsErrorTrackingAssignmentRulesRetrieveResponseSuccess =
    environmentsErrorTrackingAssignmentRulesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesRetrieveResponse =
    environmentsErrorTrackingAssignmentRulesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesRetrieveResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesUpdateResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type environmentsErrorTrackingAssignmentRulesUpdateResponseSuccess =
    environmentsErrorTrackingAssignmentRulesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesUpdateResponse =
    environmentsErrorTrackingAssignmentRulesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingAssignmentRuleApi: NonReadonly<ErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesUpdateResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingAssignmentRuleApi),
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesPartialUpdateResponse200 = {
    data: ErrorTrackingAssignmentRuleApi
    status: 200
}

export type environmentsErrorTrackingAssignmentRulesPartialUpdateResponseSuccess =
    environmentsErrorTrackingAssignmentRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesPartialUpdateResponse =
    environmentsErrorTrackingAssignmentRulesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsErrorTrackingAssignmentRulesDestroyResponseSuccess =
    environmentsErrorTrackingAssignmentRulesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesDestroyResponse =
    environmentsErrorTrackingAssignmentRulesDestroyResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/${id}/`
}

export const environmentsErrorTrackingAssignmentRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesDestroyResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponseSuccess =
    environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponse =
    environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingAssignmentRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/assignment_rules/reorder/`
}

export const environmentsErrorTrackingAssignmentRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingAssignmentRuleApi: NonReadonly<PatchedErrorTrackingAssignmentRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingAssignmentRulesReorderPartialUpdateResponse>(
        getEnvironmentsErrorTrackingAssignmentRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingAssignmentRuleApi),
        }
    )
}

export type environmentsErrorTrackingExternalReferencesListResponse200 = {
    data: PaginatedErrorTrackingExternalReferenceListApi
    status: 200
}

export type environmentsErrorTrackingExternalReferencesListResponseSuccess =
    environmentsErrorTrackingExternalReferencesListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingExternalReferencesListResponse =
    environmentsErrorTrackingExternalReferencesListResponseSuccess

export const getEnvironmentsErrorTrackingExternalReferencesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingExternalReferencesListParams
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

export const environmentsErrorTrackingExternalReferencesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingExternalReferencesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesListResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesListResponse>(
        getEnvironmentsErrorTrackingExternalReferencesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingExternalReferencesCreateResponse201 = {
    data: ErrorTrackingExternalReferenceApi
    status: 201
}

export type environmentsErrorTrackingExternalReferencesCreateResponseSuccess =
    environmentsErrorTrackingExternalReferencesCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingExternalReferencesCreateResponse =
    environmentsErrorTrackingExternalReferencesCreateResponseSuccess

export const getEnvironmentsErrorTrackingExternalReferencesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/`
}

export const environmentsErrorTrackingExternalReferencesCreate = async (
    projectId: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesCreateResponse>(
        getEnvironmentsErrorTrackingExternalReferencesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export type environmentsErrorTrackingExternalReferencesRetrieveResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type environmentsErrorTrackingExternalReferencesRetrieveResponseSuccess =
    environmentsErrorTrackingExternalReferencesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingExternalReferencesRetrieveResponse =
    environmentsErrorTrackingExternalReferencesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingExternalReferencesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesRetrieveResponse>(
        getEnvironmentsErrorTrackingExternalReferencesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingExternalReferencesUpdateResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type environmentsErrorTrackingExternalReferencesUpdateResponseSuccess =
    environmentsErrorTrackingExternalReferencesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingExternalReferencesUpdateResponse =
    environmentsErrorTrackingExternalReferencesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingExternalReferencesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingExternalReferenceApi: NonReadonly<ErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesUpdateResponse>(
        getEnvironmentsErrorTrackingExternalReferencesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingExternalReferenceApi),
        }
    )
}

export type environmentsErrorTrackingExternalReferencesPartialUpdateResponse200 = {
    data: ErrorTrackingExternalReferenceApi
    status: 200
}

export type environmentsErrorTrackingExternalReferencesPartialUpdateResponseSuccess =
    environmentsErrorTrackingExternalReferencesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingExternalReferencesPartialUpdateResponse =
    environmentsErrorTrackingExternalReferencesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingExternalReferencesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingExternalReferenceApi: NonReadonly<PatchedErrorTrackingExternalReferenceApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingExternalReferencesPartialUpdateUrl(projectId, id),
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
export type environmentsErrorTrackingExternalReferencesDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsErrorTrackingExternalReferencesDestroyResponseError =
    environmentsErrorTrackingExternalReferencesDestroyResponse405 & {
        headers: Headers
    }

export type environmentsErrorTrackingExternalReferencesDestroyResponse =
    environmentsErrorTrackingExternalReferencesDestroyResponseError

export const getEnvironmentsErrorTrackingExternalReferencesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/external_references/${id}/`
}

export const environmentsErrorTrackingExternalReferencesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingExternalReferencesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingExternalReferencesDestroyResponse>(
        getEnvironmentsErrorTrackingExternalReferencesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingFingerprintsListResponse200 = {
    data: PaginatedErrorTrackingFingerprintListApi
    status: 200
}

export type environmentsErrorTrackingFingerprintsListResponseSuccess =
    environmentsErrorTrackingFingerprintsListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingFingerprintsListResponse = environmentsErrorTrackingFingerprintsListResponseSuccess

export const getEnvironmentsErrorTrackingFingerprintsListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingFingerprintsListParams
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

export const environmentsErrorTrackingFingerprintsList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingFingerprintsListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingFingerprintsListResponse> => {
    return apiMutator<environmentsErrorTrackingFingerprintsListResponse>(
        getEnvironmentsErrorTrackingFingerprintsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingFingerprintsRetrieveResponse200 = {
    data: ErrorTrackingFingerprintApi
    status: 200
}

export type environmentsErrorTrackingFingerprintsRetrieveResponseSuccess =
    environmentsErrorTrackingFingerprintsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingFingerprintsRetrieveResponse =
    environmentsErrorTrackingFingerprintsRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingFingerprintsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const environmentsErrorTrackingFingerprintsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingFingerprintsRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingFingerprintsRetrieveResponse>(
        getEnvironmentsErrorTrackingFingerprintsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsErrorTrackingFingerprintsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsErrorTrackingFingerprintsDestroyResponseError =
    environmentsErrorTrackingFingerprintsDestroyResponse405 & {
        headers: Headers
    }

export type environmentsErrorTrackingFingerprintsDestroyResponse =
    environmentsErrorTrackingFingerprintsDestroyResponseError

export const getEnvironmentsErrorTrackingFingerprintsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/fingerprints/${id}/`
}

export const environmentsErrorTrackingFingerprintsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingFingerprintsDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingFingerprintsDestroyResponse>(
        getEnvironmentsErrorTrackingFingerprintsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponseSuccess =
    environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponse =
    environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_github/`
}

export const environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveResponse>(
        getEnvironmentsErrorTrackingGitProviderFileLinksResolveGithubRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponseSuccess =
    environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse =
    environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/git-provider-file-links/resolve_gitlab/`
}

export const environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveResponse>(
        getEnvironmentsErrorTrackingGitProviderFileLinksResolveGitlabRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingGroupingRulesListResponse200 = {
    data: PaginatedErrorTrackingGroupingRuleListApi
    status: 200
}

export type environmentsErrorTrackingGroupingRulesListResponseSuccess =
    environmentsErrorTrackingGroupingRulesListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesListResponse =
    environmentsErrorTrackingGroupingRulesListResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingGroupingRulesListParams
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

export const environmentsErrorTrackingGroupingRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingGroupingRulesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesListResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesListResponse>(
        getEnvironmentsErrorTrackingGroupingRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingGroupingRulesCreateResponse201 = {
    data: ErrorTrackingGroupingRuleApi
    status: 201
}

export type environmentsErrorTrackingGroupingRulesCreateResponseSuccess =
    environmentsErrorTrackingGroupingRulesCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesCreateResponse =
    environmentsErrorTrackingGroupingRulesCreateResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/`
}

export const environmentsErrorTrackingGroupingRulesCreate = async (
    projectId: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesCreateResponse>(
        getEnvironmentsErrorTrackingGroupingRulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingGroupingRuleApi),
        }
    )
}

export type environmentsErrorTrackingGroupingRulesRetrieveResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type environmentsErrorTrackingGroupingRulesRetrieveResponseSuccess =
    environmentsErrorTrackingGroupingRulesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesRetrieveResponse =
    environmentsErrorTrackingGroupingRulesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesRetrieveResponse>(
        getEnvironmentsErrorTrackingGroupingRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingGroupingRulesUpdateResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type environmentsErrorTrackingGroupingRulesUpdateResponseSuccess =
    environmentsErrorTrackingGroupingRulesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesUpdateResponse =
    environmentsErrorTrackingGroupingRulesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingGroupingRuleApi: NonReadonly<ErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesUpdateResponse>(
        getEnvironmentsErrorTrackingGroupingRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingGroupingRuleApi),
        }
    )
}

export type environmentsErrorTrackingGroupingRulesPartialUpdateResponse200 = {
    data: ErrorTrackingGroupingRuleApi
    status: 200
}

export type environmentsErrorTrackingGroupingRulesPartialUpdateResponseSuccess =
    environmentsErrorTrackingGroupingRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesPartialUpdateResponse =
    environmentsErrorTrackingGroupingRulesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingGroupingRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
        }
    )
}

export type environmentsErrorTrackingGroupingRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsErrorTrackingGroupingRulesDestroyResponseSuccess =
    environmentsErrorTrackingGroupingRulesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesDestroyResponse =
    environmentsErrorTrackingGroupingRulesDestroyResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/${id}/`
}

export const environmentsErrorTrackingGroupingRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesDestroyResponse>(
        getEnvironmentsErrorTrackingGroupingRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponseSuccess =
    environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponse =
    environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingGroupingRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/grouping_rules/reorder/`
}

export const environmentsErrorTrackingGroupingRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingGroupingRuleApi: NonReadonly<PatchedErrorTrackingGroupingRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingGroupingRulesReorderPartialUpdateResponse>(
        getEnvironmentsErrorTrackingGroupingRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingGroupingRuleApi),
        }
    )
}

export type environmentsErrorTrackingIssuesListResponse200 = {
    data: PaginatedErrorTrackingIssueFullListApi
    status: 200
}

export type environmentsErrorTrackingIssuesListResponseSuccess = environmentsErrorTrackingIssuesListResponse200 & {
    headers: Headers
}
export type environmentsErrorTrackingIssuesListResponse = environmentsErrorTrackingIssuesListResponseSuccess

export const getEnvironmentsErrorTrackingIssuesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingIssuesListParams
) => {
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

export const environmentsErrorTrackingIssuesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingIssuesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesListResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesListResponse>(
        getEnvironmentsErrorTrackingIssuesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingIssuesCreateResponse201 = {
    data: ErrorTrackingIssueFullApi
    status: 201
}

export type environmentsErrorTrackingIssuesCreateResponseSuccess = environmentsErrorTrackingIssuesCreateResponse201 & {
    headers: Headers
}
export type environmentsErrorTrackingIssuesCreateResponse = environmentsErrorTrackingIssuesCreateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/`
}

export const environmentsErrorTrackingIssuesCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesCreateResponse>(
        getEnvironmentsErrorTrackingIssuesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesRetrieveResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type environmentsErrorTrackingIssuesRetrieveResponseSuccess =
    environmentsErrorTrackingIssuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesRetrieveResponse = environmentsErrorTrackingIssuesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingIssuesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesRetrieveResponse>(
        getEnvironmentsErrorTrackingIssuesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingIssuesUpdateResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type environmentsErrorTrackingIssuesUpdateResponseSuccess = environmentsErrorTrackingIssuesUpdateResponse200 & {
    headers: Headers
}
export type environmentsErrorTrackingIssuesUpdateResponse = environmentsErrorTrackingIssuesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesUpdateResponse>(
        getEnvironmentsErrorTrackingIssuesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesPartialUpdateResponse200 = {
    data: ErrorTrackingIssueFullApi
    status: 200
}

export type environmentsErrorTrackingIssuesPartialUpdateResponseSuccess =
    environmentsErrorTrackingIssuesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesPartialUpdateResponse =
    environmentsErrorTrackingIssuesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingIssuesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingIssueFullApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsErrorTrackingIssuesDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsErrorTrackingIssuesDestroyResponseError = environmentsErrorTrackingIssuesDestroyResponse405 & {
    headers: Headers
}

export type environmentsErrorTrackingIssuesDestroyResponse = environmentsErrorTrackingIssuesDestroyResponseError

export const getEnvironmentsErrorTrackingIssuesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/`
}

export const environmentsErrorTrackingIssuesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesDestroyResponse>(
        getEnvironmentsErrorTrackingIssuesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingIssuesActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesActivityRetrieve2ResponseSuccess =
    environmentsErrorTrackingIssuesActivityRetrieve2Response200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesActivityRetrieve2Response =
    environmentsErrorTrackingIssuesActivityRetrieve2ResponseSuccess

export const getEnvironmentsErrorTrackingIssuesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/activity/`
}

export const environmentsErrorTrackingIssuesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesActivityRetrieve2Response> => {
    return apiMutator<environmentsErrorTrackingIssuesActivityRetrieve2Response>(
        getEnvironmentsErrorTrackingIssuesActivityRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingIssuesAssignPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesAssignPartialUpdateResponseSuccess =
    environmentsErrorTrackingIssuesAssignPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesAssignPartialUpdateResponse =
    environmentsErrorTrackingIssuesAssignPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesAssignPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/assign/`
}

export const environmentsErrorTrackingIssuesAssignPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingIssueFullApi: NonReadonly<PatchedErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesAssignPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesAssignPartialUpdateResponse>(
        getEnvironmentsErrorTrackingIssuesAssignPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesCohortUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesCohortUpdateResponseSuccess =
    environmentsErrorTrackingIssuesCohortUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesCohortUpdateResponse =
    environmentsErrorTrackingIssuesCohortUpdateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesCohortUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/cohort/`
}

export const environmentsErrorTrackingIssuesCohortUpdate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesCohortUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesCohortUpdateResponse>(
        getEnvironmentsErrorTrackingIssuesCohortUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesMergeCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesMergeCreateResponseSuccess =
    environmentsErrorTrackingIssuesMergeCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesMergeCreateResponse =
    environmentsErrorTrackingIssuesMergeCreateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesMergeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/merge/`
}

export const environmentsErrorTrackingIssuesMergeCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesMergeCreateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesMergeCreateResponse>(
        getEnvironmentsErrorTrackingIssuesMergeCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesSplitCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesSplitCreateResponseSuccess =
    environmentsErrorTrackingIssuesSplitCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesSplitCreateResponse =
    environmentsErrorTrackingIssuesSplitCreateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesSplitCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/${id}/split/`
}

export const environmentsErrorTrackingIssuesSplitCreate = async (
    projectId: string,
    id: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesSplitCreateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesSplitCreateResponse>(
        getEnvironmentsErrorTrackingIssuesSplitCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesActivityRetrieveResponseSuccess =
    environmentsErrorTrackingIssuesActivityRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesActivityRetrieveResponse =
    environmentsErrorTrackingIssuesActivityRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingIssuesActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/activity/`
}

export const environmentsErrorTrackingIssuesActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesActivityRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesActivityRetrieveResponse>(
        getEnvironmentsErrorTrackingIssuesActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingIssuesBulkCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesBulkCreateResponseSuccess =
    environmentsErrorTrackingIssuesBulkCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesBulkCreateResponse = environmentsErrorTrackingIssuesBulkCreateResponseSuccess

export const getEnvironmentsErrorTrackingIssuesBulkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/bulk/`
}

export const environmentsErrorTrackingIssuesBulkCreate = async (
    projectId: string,
    errorTrackingIssueFullApi: NonReadonly<ErrorTrackingIssueFullApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesBulkCreateResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesBulkCreateResponse>(
        getEnvironmentsErrorTrackingIssuesBulkCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingIssueFullApi),
        }
    )
}

export type environmentsErrorTrackingIssuesValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingIssuesValuesRetrieveResponseSuccess =
    environmentsErrorTrackingIssuesValuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingIssuesValuesRetrieveResponse =
    environmentsErrorTrackingIssuesValuesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingIssuesValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/issues/values/`
}

export const environmentsErrorTrackingIssuesValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingIssuesValuesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingIssuesValuesRetrieveResponse>(
        getEnvironmentsErrorTrackingIssuesValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingReleasesListResponse200 = {
    data: PaginatedErrorTrackingReleaseListApi
    status: 200
}

export type environmentsErrorTrackingReleasesListResponseSuccess = environmentsErrorTrackingReleasesListResponse200 & {
    headers: Headers
}
export type environmentsErrorTrackingReleasesListResponse = environmentsErrorTrackingReleasesListResponseSuccess

export const getEnvironmentsErrorTrackingReleasesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingReleasesListParams
) => {
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

export const environmentsErrorTrackingReleasesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingReleasesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesListResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesListResponse>(
        getEnvironmentsErrorTrackingReleasesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingReleasesCreateResponse201 = {
    data: ErrorTrackingReleaseApi
    status: 201
}

export type environmentsErrorTrackingReleasesCreateResponseSuccess =
    environmentsErrorTrackingReleasesCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesCreateResponse = environmentsErrorTrackingReleasesCreateResponseSuccess

export const getEnvironmentsErrorTrackingReleasesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/`
}

export const environmentsErrorTrackingReleasesCreate = async (
    projectId: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesCreateResponse>(
        getEnvironmentsErrorTrackingReleasesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingReleaseApi),
        }
    )
}

export type environmentsErrorTrackingReleasesRetrieveResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type environmentsErrorTrackingReleasesRetrieveResponseSuccess =
    environmentsErrorTrackingReleasesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesRetrieveResponse = environmentsErrorTrackingReleasesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingReleasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesRetrieveResponse>(
        getEnvironmentsErrorTrackingReleasesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingReleasesUpdateResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type environmentsErrorTrackingReleasesUpdateResponseSuccess =
    environmentsErrorTrackingReleasesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesUpdateResponse = environmentsErrorTrackingReleasesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingReleasesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingReleaseApi: NonReadonly<ErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesUpdateResponse>(
        getEnvironmentsErrorTrackingReleasesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingReleaseApi),
        }
    )
}

export type environmentsErrorTrackingReleasesPartialUpdateResponse200 = {
    data: ErrorTrackingReleaseApi
    status: 200
}

export type environmentsErrorTrackingReleasesPartialUpdateResponseSuccess =
    environmentsErrorTrackingReleasesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesPartialUpdateResponse =
    environmentsErrorTrackingReleasesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingReleasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingReleaseApi: NonReadonly<PatchedErrorTrackingReleaseApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingReleasesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingReleaseApi),
        }
    )
}

export type environmentsErrorTrackingReleasesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsErrorTrackingReleasesDestroyResponseSuccess =
    environmentsErrorTrackingReleasesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesDestroyResponse = environmentsErrorTrackingReleasesDestroyResponseSuccess

export const getEnvironmentsErrorTrackingReleasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/${id}/`
}

export const environmentsErrorTrackingReleasesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesDestroyResponse>(
        getEnvironmentsErrorTrackingReleasesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingReleasesHashRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingReleasesHashRetrieveResponseSuccess =
    environmentsErrorTrackingReleasesHashRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingReleasesHashRetrieveResponse =
    environmentsErrorTrackingReleasesHashRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingReleasesHashRetrieveUrl = (projectId: string, hashId: string) => {
    return `/api/environments/${projectId}/error_tracking/releases/hash/${hashId}/`
}

export const environmentsErrorTrackingReleasesHashRetrieve = async (
    projectId: string,
    hashId: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingReleasesHashRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingReleasesHashRetrieveResponse>(
        getEnvironmentsErrorTrackingReleasesHashRetrieveUrl(projectId, hashId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingStackFramesListResponse200 = {
    data: PaginatedErrorTrackingStackFrameListApi
    status: 200
}

export type environmentsErrorTrackingStackFramesListResponseSuccess =
    environmentsErrorTrackingStackFramesListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingStackFramesListResponse = environmentsErrorTrackingStackFramesListResponseSuccess

export const getEnvironmentsErrorTrackingStackFramesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingStackFramesListParams
) => {
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

export const environmentsErrorTrackingStackFramesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingStackFramesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingStackFramesListResponse> => {
    return apiMutator<environmentsErrorTrackingStackFramesListResponse>(
        getEnvironmentsErrorTrackingStackFramesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingStackFramesRetrieveResponse200 = {
    data: ErrorTrackingStackFrameApi
    status: 200
}

export type environmentsErrorTrackingStackFramesRetrieveResponseSuccess =
    environmentsErrorTrackingStackFramesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingStackFramesRetrieveResponse =
    environmentsErrorTrackingStackFramesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingStackFramesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const environmentsErrorTrackingStackFramesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingStackFramesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingStackFramesRetrieveResponse>(
        getEnvironmentsErrorTrackingStackFramesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsErrorTrackingStackFramesDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsErrorTrackingStackFramesDestroyResponseError =
    environmentsErrorTrackingStackFramesDestroyResponse405 & {
        headers: Headers
    }

export type environmentsErrorTrackingStackFramesDestroyResponse =
    environmentsErrorTrackingStackFramesDestroyResponseError

export const getEnvironmentsErrorTrackingStackFramesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/${id}/`
}

export const environmentsErrorTrackingStackFramesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingStackFramesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingStackFramesDestroyResponse>(
        getEnvironmentsErrorTrackingStackFramesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingStackFramesBatchGetCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingStackFramesBatchGetCreateResponseSuccess =
    environmentsErrorTrackingStackFramesBatchGetCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingStackFramesBatchGetCreateResponse =
    environmentsErrorTrackingStackFramesBatchGetCreateResponseSuccess

export const getEnvironmentsErrorTrackingStackFramesBatchGetCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/stack_frames/batch_get/`
}

export const environmentsErrorTrackingStackFramesBatchGetCreate = async (
    projectId: string,
    errorTrackingStackFrameApi: NonReadonly<ErrorTrackingStackFrameApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingStackFramesBatchGetCreateResponse> => {
    return apiMutator<environmentsErrorTrackingStackFramesBatchGetCreateResponse>(
        getEnvironmentsErrorTrackingStackFramesBatchGetCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingStackFrameApi),
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesListResponse200 = {
    data: PaginatedErrorTrackingSuppressionRuleListApi
    status: 200
}

export type environmentsErrorTrackingSuppressionRulesListResponseSuccess =
    environmentsErrorTrackingSuppressionRulesListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesListResponse =
    environmentsErrorTrackingSuppressionRulesListResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingSuppressionRulesListParams
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

export const environmentsErrorTrackingSuppressionRulesList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingSuppressionRulesListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesListResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesListResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesCreateResponse201 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 201
}

export type environmentsErrorTrackingSuppressionRulesCreateResponseSuccess =
    environmentsErrorTrackingSuppressionRulesCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesCreateResponse =
    environmentsErrorTrackingSuppressionRulesCreateResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/`
}

export const environmentsErrorTrackingSuppressionRulesCreate = async (
    projectId: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesCreateResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesCreateResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesRetrieveResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type environmentsErrorTrackingSuppressionRulesRetrieveResponseSuccess =
    environmentsErrorTrackingSuppressionRulesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesRetrieveResponse =
    environmentsErrorTrackingSuppressionRulesRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesRetrieveResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesUpdateResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type environmentsErrorTrackingSuppressionRulesUpdateResponseSuccess =
    environmentsErrorTrackingSuppressionRulesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesUpdateResponse =
    environmentsErrorTrackingSuppressionRulesUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSuppressionRuleApi: NonReadonly<ErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesUpdateResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSuppressionRuleApi),
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesPartialUpdateResponse200 = {
    data: ErrorTrackingSuppressionRuleApi
    status: 200
}

export type environmentsErrorTrackingSuppressionRulesPartialUpdateResponseSuccess =
    environmentsErrorTrackingSuppressionRulesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesPartialUpdateResponse =
    environmentsErrorTrackingSuppressionRulesPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesPartialUpdateResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsErrorTrackingSuppressionRulesDestroyResponseSuccess =
    environmentsErrorTrackingSuppressionRulesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesDestroyResponse =
    environmentsErrorTrackingSuppressionRulesDestroyResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/${id}/`
}

export const environmentsErrorTrackingSuppressionRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesDestroyResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponseSuccess =
    environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponse =
    environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSuppressionRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/suppression_rules/reorder/`
}

export const environmentsErrorTrackingSuppressionRulesReorderPartialUpdate = async (
    projectId: string,
    patchedErrorTrackingSuppressionRuleApi: NonReadonly<PatchedErrorTrackingSuppressionRuleApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSuppressionRulesReorderPartialUpdateResponse>(
        getEnvironmentsErrorTrackingSuppressionRulesReorderPartialUpdateUrl(projectId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedErrorTrackingSuppressionRuleApi),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsListResponse200 = {
    data: PaginatedErrorTrackingSymbolSetListApi
    status: 200
}

export type environmentsErrorTrackingSymbolSetsListResponseSuccess =
    environmentsErrorTrackingSymbolSetsListResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsListResponse = environmentsErrorTrackingSymbolSetsListResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsListUrl = (
    projectId: string,
    params?: EnvironmentsErrorTrackingSymbolSetsListParams
) => {
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

export const environmentsErrorTrackingSymbolSetsList = async (
    projectId: string,
    params?: EnvironmentsErrorTrackingSymbolSetsListParams,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsListResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsListResponse>(
        getEnvironmentsErrorTrackingSymbolSetsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingSymbolSetsCreateResponse201 = {
    data: ErrorTrackingSymbolSetApi
    status: 201
}

export type environmentsErrorTrackingSymbolSetsCreateResponseSuccess =
    environmentsErrorTrackingSymbolSetsCreateResponse201 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsCreateResponse = environmentsErrorTrackingSymbolSetsCreateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/`
}

export const environmentsErrorTrackingSymbolSetsCreate = async (
    projectId: string,
    environmentsErrorTrackingSymbolSetsCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsCreateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: JSON.stringify(environmentsErrorTrackingSymbolSetsCreateBody),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsRetrieveResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type environmentsErrorTrackingSymbolSetsRetrieveResponseSuccess =
    environmentsErrorTrackingSymbolSetsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsRetrieveResponse =
    environmentsErrorTrackingSymbolSetsRetrieveResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsRetrieveResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsRetrieveResponse>(
        getEnvironmentsErrorTrackingSymbolSetsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsErrorTrackingSymbolSetsUpdateResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type environmentsErrorTrackingSymbolSetsUpdateResponseSuccess =
    environmentsErrorTrackingSymbolSetsUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsUpdateResponse = environmentsErrorTrackingSymbolSetsUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsUpdate = async (
    projectId: string,
    id: string,
    environmentsErrorTrackingSymbolSetsUpdateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsUpdateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            body: JSON.stringify(environmentsErrorTrackingSymbolSetsUpdateBody),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsPartialUpdateResponse200 = {
    data: ErrorTrackingSymbolSetApi
    status: 200
}

export type environmentsErrorTrackingSymbolSetsPartialUpdateResponseSuccess =
    environmentsErrorTrackingSymbolSetsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsPartialUpdateResponse =
    environmentsErrorTrackingSymbolSetsPartialUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsPartialUpdate = async (
    projectId: string,
    id: string,
    environmentsErrorTrackingSymbolSetsPartialUpdateBody: NonReadonly<PatchedErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsPartialUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsPartialUpdateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: JSON.stringify(environmentsErrorTrackingSymbolSetsPartialUpdateBody),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsErrorTrackingSymbolSetsDestroyResponseSuccess =
    environmentsErrorTrackingSymbolSetsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsDestroyResponse =
    environmentsErrorTrackingSymbolSetsDestroyResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/`
}

export const environmentsErrorTrackingSymbolSetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsDestroyResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsDestroyResponse>(
        getEnvironmentsErrorTrackingSymbolSetsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponseSuccess =
    environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponse =
    environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsFinishUploadUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
}

export const environmentsErrorTrackingSymbolSetsFinishUploadUpdate = async (
    projectId: string,
    id: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsFinishUploadUpdateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsFinishUploadUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponseSuccess =
    environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponse =
    environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsBulkFinishUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
}

export const environmentsErrorTrackingSymbolSetsBulkFinishUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsBulkFinishUploadCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsBulkFinishUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponseSuccess =
    environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponse =
    environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsBulkStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
}

export const environmentsErrorTrackingSymbolSetsBulkStartUploadCreate = async (
    projectId: string,
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsBulkStartUploadCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsBulkStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(errorTrackingSymbolSetApi),
        }
    )
}

export type environmentsErrorTrackingSymbolSetsStartUploadCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsErrorTrackingSymbolSetsStartUploadCreateResponseSuccess =
    environmentsErrorTrackingSymbolSetsStartUploadCreateResponse200 & {
        headers: Headers
    }
export type environmentsErrorTrackingSymbolSetsStartUploadCreateResponse =
    environmentsErrorTrackingSymbolSetsStartUploadCreateResponseSuccess

export const getEnvironmentsErrorTrackingSymbolSetsStartUploadCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/error_tracking/symbol_sets/start_upload/`
}

export const environmentsErrorTrackingSymbolSetsStartUploadCreate = async (
    projectId: string,
    environmentsErrorTrackingSymbolSetsStartUploadCreateBody: NonReadonly<ErrorTrackingSymbolSetApi | Blob>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsStartUploadCreateResponse> => {
    return apiMutator<environmentsErrorTrackingSymbolSetsStartUploadCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: JSON.stringify(environmentsErrorTrackingSymbolSetsStartUploadCreateBody),
        }
    )
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
        ? `/api/projects/${projectId}/error_tracking/releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/releases/`
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
    return `/api/projects/${projectId}/error_tracking/releases/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/releases/hash/${hashId}/`
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
        ? `/api/projects/${projectId}/error_tracking/symbol_sets/?${stringifiedParams}`
        : `/api/projects/${projectId}/error_tracking/symbol_sets/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/${id}/finish_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_finish_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/bulk_start_upload/`
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
    return `/api/projects/${projectId}/error_tracking/symbol_sets/start_upload/`
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
