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
    EnvironmentsErrorTrackingFingerprintsListParams,
    EnvironmentsErrorTrackingIssuesListParams,
    EnvironmentsErrorTrackingReleasesListParams,
    EnvironmentsErrorTrackingStackFramesListParams,
    EnvironmentsErrorTrackingSymbolSetsListParams,
    ErrorTrackingFingerprintApi,
    ErrorTrackingIssueFullApi,
    ErrorTrackingReleaseApi,
    ErrorTrackingReleasesListParams,
    ErrorTrackingStackFrameApi,
    ErrorTrackingSymbolSetApi,
    ErrorTrackingSymbolSetsListParams,
    PaginatedErrorTrackingFingerprintListApi,
    PaginatedErrorTrackingIssueFullListApi,
    PaginatedErrorTrackingReleaseListApi,
    PaginatedErrorTrackingStackFrameListApi,
    PaginatedErrorTrackingSymbolSetListApi,
    PatchedErrorTrackingIssueFullApi,
    PatchedErrorTrackingReleaseApi,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsCreateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<environmentsErrorTrackingSymbolSetsCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: formData,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsUpdateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<environmentsErrorTrackingSymbolSetsUpdateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            body: formData,
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
    patchedErrorTrackingSymbolSetApi: NonReadonly<PatchedErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsPartialUpdateResponse> => {
    const formData = new FormData()
    if (patchedErrorTrackingSymbolSetApi.ref !== undefined) {
        formData.append(`ref`, patchedErrorTrackingSymbolSetApi.ref)
    }
    if (
        patchedErrorTrackingSymbolSetApi.last_used !== undefined &&
        patchedErrorTrackingSymbolSetApi.last_used !== null
    ) {
        formData.append(`last_used`, patchedErrorTrackingSymbolSetApi.last_used)
    }
    if (
        patchedErrorTrackingSymbolSetApi.storage_ptr !== undefined &&
        patchedErrorTrackingSymbolSetApi.storage_ptr !== null
    ) {
        formData.append(`storage_ptr`, patchedErrorTrackingSymbolSetApi.storage_ptr)
    }
    if (
        patchedErrorTrackingSymbolSetApi.failure_reason !== undefined &&
        patchedErrorTrackingSymbolSetApi.failure_reason !== null
    ) {
        formData.append(`failure_reason`, patchedErrorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<environmentsErrorTrackingSymbolSetsPartialUpdateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: formData,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<environmentsErrorTrackingSymbolSetsStartUploadCreateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<environmentsErrorTrackingSymbolSetsStartUploadCreateResponse>(
        getEnvironmentsErrorTrackingSymbolSetsStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: formData,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsCreateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<errorTrackingSymbolSetsCreateResponse>(getErrorTrackingSymbolSetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsUpdateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<errorTrackingSymbolSetsUpdateResponse>(getErrorTrackingSymbolSetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        body: formData,
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
    patchedErrorTrackingSymbolSetApi: NonReadonly<PatchedErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsPartialUpdateResponse> => {
    const formData = new FormData()
    if (patchedErrorTrackingSymbolSetApi.ref !== undefined) {
        formData.append(`ref`, patchedErrorTrackingSymbolSetApi.ref)
    }
    if (
        patchedErrorTrackingSymbolSetApi.last_used !== undefined &&
        patchedErrorTrackingSymbolSetApi.last_used !== null
    ) {
        formData.append(`last_used`, patchedErrorTrackingSymbolSetApi.last_used)
    }
    if (
        patchedErrorTrackingSymbolSetApi.storage_ptr !== undefined &&
        patchedErrorTrackingSymbolSetApi.storage_ptr !== null
    ) {
        formData.append(`storage_ptr`, patchedErrorTrackingSymbolSetApi.storage_ptr)
    }
    if (
        patchedErrorTrackingSymbolSetApi.failure_reason !== undefined &&
        patchedErrorTrackingSymbolSetApi.failure_reason !== null
    ) {
        formData.append(`failure_reason`, patchedErrorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<errorTrackingSymbolSetsPartialUpdateResponse>(
        getErrorTrackingSymbolSetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            body: formData,
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
    errorTrackingSymbolSetApi: NonReadonly<ErrorTrackingSymbolSetApi>,
    options?: RequestInit
): Promise<errorTrackingSymbolSetsStartUploadCreateResponse> => {
    const formData = new FormData()
    formData.append(`ref`, errorTrackingSymbolSetApi.ref)
    if (errorTrackingSymbolSetApi.last_used !== undefined && errorTrackingSymbolSetApi.last_used !== null) {
        formData.append(`last_used`, errorTrackingSymbolSetApi.last_used)
    }
    if (errorTrackingSymbolSetApi.storage_ptr !== undefined && errorTrackingSymbolSetApi.storage_ptr !== null) {
        formData.append(`storage_ptr`, errorTrackingSymbolSetApi.storage_ptr)
    }
    if (errorTrackingSymbolSetApi.failure_reason !== undefined && errorTrackingSymbolSetApi.failure_reason !== null) {
        formData.append(`failure_reason`, errorTrackingSymbolSetApi.failure_reason)
    }

    return apiMutator<errorTrackingSymbolSetsStartUploadCreateResponse>(
        getErrorTrackingSymbolSetsStartUploadCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: formData,
        }
    )
}
