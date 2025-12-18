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
    AppendSegmentsApi,
    CreateRecordingRequestApi,
    CreateRecordingResponseApi,
    DesktopRecordingApi,
    EnvironmentsDesktopRecordingsListParams,
    PaginatedDesktopRecordingListApi,
    PatchedDesktopRecordingApi,
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

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export type environmentsDesktopRecordingsListResponse200 = {
    data: PaginatedDesktopRecordingListApi
    status: 200
}

export type environmentsDesktopRecordingsListResponseSuccess = environmentsDesktopRecordingsListResponse200 & {
    headers: Headers
}
export type environmentsDesktopRecordingsListResponse = environmentsDesktopRecordingsListResponseSuccess

export const getEnvironmentsDesktopRecordingsListUrl = (
    projectId: string,
    params?: EnvironmentsDesktopRecordingsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/desktop_recordings/?${stringifiedParams}`
        : `/api/environments/${projectId}/desktop_recordings/`
}

export const environmentsDesktopRecordingsList = async (
    projectId: string,
    params?: EnvironmentsDesktopRecordingsListParams,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsListResponse> => {
    return apiMutator<environmentsDesktopRecordingsListResponse>(
        getEnvironmentsDesktopRecordingsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new recording and get Recall.ai upload token for the desktop SDK
 */
export type environmentsDesktopRecordingsCreateResponse201 = {
    data: CreateRecordingResponseApi
    status: 201
}

export type environmentsDesktopRecordingsCreateResponseSuccess = environmentsDesktopRecordingsCreateResponse201 & {
    headers: Headers
}
export type environmentsDesktopRecordingsCreateResponse = environmentsDesktopRecordingsCreateResponseSuccess

export const getEnvironmentsDesktopRecordingsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/desktop_recordings/`
}

export const environmentsDesktopRecordingsCreate = async (
    projectId: string,
    createRecordingRequestApi: CreateRecordingRequestApi,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsCreateResponse> => {
    return apiMutator<environmentsDesktopRecordingsCreateResponse>(
        getEnvironmentsDesktopRecordingsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(createRecordingRequestApi),
        }
    )
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export type environmentsDesktopRecordingsRetrieveResponse200 = {
    data: DesktopRecordingApi
    status: 200
}

export type environmentsDesktopRecordingsRetrieveResponseSuccess = environmentsDesktopRecordingsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDesktopRecordingsRetrieveResponse = environmentsDesktopRecordingsRetrieveResponseSuccess

export const getEnvironmentsDesktopRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const environmentsDesktopRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsRetrieveResponse> => {
    return apiMutator<environmentsDesktopRecordingsRetrieveResponse>(
        getEnvironmentsDesktopRecordingsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export type environmentsDesktopRecordingsUpdateResponse200 = {
    data: DesktopRecordingApi
    status: 200
}

export type environmentsDesktopRecordingsUpdateResponseSuccess = environmentsDesktopRecordingsUpdateResponse200 & {
    headers: Headers
}
export type environmentsDesktopRecordingsUpdateResponse = environmentsDesktopRecordingsUpdateResponseSuccess

export const getEnvironmentsDesktopRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const environmentsDesktopRecordingsUpdate = async (
    projectId: string,
    id: string,
    desktopRecordingApi: NonReadonly<DesktopRecordingApi>,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsUpdateResponse> => {
    return apiMutator<environmentsDesktopRecordingsUpdateResponse>(
        getEnvironmentsDesktopRecordingsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(desktopRecordingApi),
        }
    )
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export type environmentsDesktopRecordingsPartialUpdateResponse200 = {
    data: DesktopRecordingApi
    status: 200
}

export type environmentsDesktopRecordingsPartialUpdateResponseSuccess =
    environmentsDesktopRecordingsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsDesktopRecordingsPartialUpdateResponse =
    environmentsDesktopRecordingsPartialUpdateResponseSuccess

export const getEnvironmentsDesktopRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const environmentsDesktopRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDesktopRecordingApi: NonReadonly<PatchedDesktopRecordingApi>,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsPartialUpdateResponse> => {
    return apiMutator<environmentsDesktopRecordingsPartialUpdateResponse>(
        getEnvironmentsDesktopRecordingsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDesktopRecordingApi),
        }
    )
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export type environmentsDesktopRecordingsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsDesktopRecordingsDestroyResponseSuccess = environmentsDesktopRecordingsDestroyResponse204 & {
    headers: Headers
}
export type environmentsDesktopRecordingsDestroyResponse = environmentsDesktopRecordingsDestroyResponseSuccess

export const getEnvironmentsDesktopRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const environmentsDesktopRecordingsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsDestroyResponse> => {
    return apiMutator<environmentsDesktopRecordingsDestroyResponse>(
        getEnvironmentsDesktopRecordingsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Append transcript segments (supports batched real-time streaming)
 */
export type environmentsDesktopRecordingsAppendSegmentsCreateResponse200 = {
    data: DesktopRecordingApi
    status: 200
}

export type environmentsDesktopRecordingsAppendSegmentsCreateResponseSuccess =
    environmentsDesktopRecordingsAppendSegmentsCreateResponse200 & {
        headers: Headers
    }
export type environmentsDesktopRecordingsAppendSegmentsCreateResponse =
    environmentsDesktopRecordingsAppendSegmentsCreateResponseSuccess

export const getEnvironmentsDesktopRecordingsAppendSegmentsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/append_segments/`
}

export const environmentsDesktopRecordingsAppendSegmentsCreate = async (
    projectId: string,
    id: string,
    appendSegmentsApi: AppendSegmentsApi,
    options?: RequestInit
): Promise<environmentsDesktopRecordingsAppendSegmentsCreateResponse> => {
    return apiMutator<environmentsDesktopRecordingsAppendSegmentsCreateResponse>(
        getEnvironmentsDesktopRecordingsAppendSegmentsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(appendSegmentsApi),
        }
    )
}
