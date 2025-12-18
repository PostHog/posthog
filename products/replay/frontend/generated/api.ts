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
    EnvironmentsSessionRecordingPlaylistsListParams,
    EnvironmentsSessionRecordingsListParams,
    PaginatedSessionRecordingListApi,
    PaginatedSessionRecordingPlaylistListApi,
    PatchedSessionRecordingApi,
    PatchedSessionRecordingPlaylistApi,
    SessionRecordingApi,
    SessionRecordingPlaylistApi,
    SessionRecordingPlaylistsListParams,
    SessionRecordingsListParams,
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
 * Override list to include synthetic playlists
 */
export type environmentsSessionRecordingPlaylistsListResponse200 = {
    data: PaginatedSessionRecordingPlaylistListApi
    status: 200
}

export type environmentsSessionRecordingPlaylistsListResponseSuccess =
    environmentsSessionRecordingPlaylistsListResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsListResponse = environmentsSessionRecordingPlaylistsListResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsListUrl = (
    projectId: string,
    params?: EnvironmentsSessionRecordingPlaylistsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/session_recording_playlists/?${stringifiedParams}`
        : `/api/environments/${projectId}/session_recording_playlists/`
}

export const environmentsSessionRecordingPlaylistsList = async (
    projectId: string,
    params?: EnvironmentsSessionRecordingPlaylistsListParams,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsListResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsListResponse>(
        getEnvironmentsSessionRecordingPlaylistsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingPlaylistsCreateResponse201 = {
    data: SessionRecordingPlaylistApi
    status: 201
}

export type environmentsSessionRecordingPlaylistsCreateResponseSuccess =
    environmentsSessionRecordingPlaylistsCreateResponse201 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsCreateResponse =
    environmentsSessionRecordingPlaylistsCreateResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/`
}

export const environmentsSessionRecordingPlaylistsCreate = async (
    projectId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsCreateResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsCreateResponse>(
        getEnvironmentsSessionRecordingPlaylistsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type environmentsSessionRecordingPlaylistsRetrieveResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type environmentsSessionRecordingPlaylistsRetrieveResponseSuccess =
    environmentsSessionRecordingPlaylistsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsRetrieveResponse =
    environmentsSessionRecordingPlaylistsRetrieveResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const environmentsSessionRecordingPlaylistsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsRetrieveResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsRetrieveResponse>(
        getEnvironmentsSessionRecordingPlaylistsRetrieveUrl(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingPlaylistsUpdateResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type environmentsSessionRecordingPlaylistsUpdateResponseSuccess =
    environmentsSessionRecordingPlaylistsUpdateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsUpdateResponse =
    environmentsSessionRecordingPlaylistsUpdateResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const environmentsSessionRecordingPlaylistsUpdate = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsUpdateResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsUpdateResponse>(
        getEnvironmentsSessionRecordingPlaylistsUpdateUrl(projectId, shortId),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type environmentsSessionRecordingPlaylistsPartialUpdateResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type environmentsSessionRecordingPlaylistsPartialUpdateResponseSuccess =
    environmentsSessionRecordingPlaylistsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsPartialUpdateResponse =
    environmentsSessionRecordingPlaylistsPartialUpdateResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const environmentsSessionRecordingPlaylistsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsPartialUpdateResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsPartialUpdateResponse>(
        getEnvironmentsSessionRecordingPlaylistsPartialUpdateUrl(projectId, shortId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedSessionRecordingPlaylistApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsSessionRecordingPlaylistsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsSessionRecordingPlaylistsDestroyResponseError =
    environmentsSessionRecordingPlaylistsDestroyResponse405 & {
        headers: Headers
    }

export type environmentsSessionRecordingPlaylistsDestroyResponse =
    environmentsSessionRecordingPlaylistsDestroyResponseError

export const getEnvironmentsSessionRecordingPlaylistsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const environmentsSessionRecordingPlaylistsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsDestroyResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsDestroyResponse>(
        getEnvironmentsSessionRecordingPlaylistsDestroyUrl(projectId, shortId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsSessionRecordingPlaylistsRecordingsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsSessionRecordingPlaylistsRecordingsRetrieveResponseSuccess =
    environmentsSessionRecordingPlaylistsRecordingsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsRecordingsRetrieveResponse =
    environmentsSessionRecordingPlaylistsRecordingsRetrieveResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsRecordingsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const environmentsSessionRecordingPlaylistsRecordingsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsRecordingsRetrieveResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsRecordingsRetrieveResponse>(
        getEnvironmentsSessionRecordingPlaylistsRecordingsRetrieveUrl(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingPlaylistsRecordingsCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsSessionRecordingPlaylistsRecordingsCreateResponseSuccess =
    environmentsSessionRecordingPlaylistsRecordingsCreateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsRecordingsCreateResponse =
    environmentsSessionRecordingPlaylistsRecordingsCreateResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsRecordingsCreateUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const environmentsSessionRecordingPlaylistsRecordingsCreate = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsRecordingsCreateResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsRecordingsCreateResponse>(
        getEnvironmentsSessionRecordingPlaylistsRecordingsCreateUrl(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type environmentsSessionRecordingPlaylistsRecordingsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsSessionRecordingPlaylistsRecordingsDestroyResponseSuccess =
    environmentsSessionRecordingPlaylistsRecordingsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsSessionRecordingPlaylistsRecordingsDestroyResponse =
    environmentsSessionRecordingPlaylistsRecordingsDestroyResponseSuccess

export const getEnvironmentsSessionRecordingPlaylistsRecordingsDestroyUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const environmentsSessionRecordingPlaylistsRecordingsDestroy = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingPlaylistsRecordingsDestroyResponse> => {
    return apiMutator<environmentsSessionRecordingPlaylistsRecordingsDestroyResponse>(
        getEnvironmentsSessionRecordingPlaylistsRecordingsDestroyUrl(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsSessionRecordingsListResponse200 = {
    data: PaginatedSessionRecordingListApi
    status: 200
}

export type environmentsSessionRecordingsListResponseSuccess = environmentsSessionRecordingsListResponse200 & {
    headers: Headers
}
export type environmentsSessionRecordingsListResponse = environmentsSessionRecordingsListResponseSuccess

export const getEnvironmentsSessionRecordingsListUrl = (
    projectId: string,
    params?: EnvironmentsSessionRecordingsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/session_recordings/?${stringifiedParams}`
        : `/api/environments/${projectId}/session_recordings/`
}

export const environmentsSessionRecordingsList = async (
    projectId: string,
    params?: EnvironmentsSessionRecordingsListParams,
    options?: RequestInit
): Promise<environmentsSessionRecordingsListResponse> => {
    return apiMutator<environmentsSessionRecordingsListResponse>(
        getEnvironmentsSessionRecordingsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingsRetrieveResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type environmentsSessionRecordingsRetrieveResponseSuccess = environmentsSessionRecordingsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsSessionRecordingsRetrieveResponse = environmentsSessionRecordingsRetrieveResponseSuccess

export const getEnvironmentsSessionRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const environmentsSessionRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingsRetrieveResponse> => {
    return apiMutator<environmentsSessionRecordingsRetrieveResponse>(
        getEnvironmentsSessionRecordingsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingsUpdateResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type environmentsSessionRecordingsUpdateResponseSuccess = environmentsSessionRecordingsUpdateResponse200 & {
    headers: Headers
}
export type environmentsSessionRecordingsUpdateResponse = environmentsSessionRecordingsUpdateResponseSuccess

export const getEnvironmentsSessionRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const environmentsSessionRecordingsUpdate = async (
    projectId: string,
    id: string,
    sessionRecordingApi: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingsUpdateResponse> => {
    return apiMutator<environmentsSessionRecordingsUpdateResponse>(
        getEnvironmentsSessionRecordingsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingApi),
        }
    )
}

export type environmentsSessionRecordingsPartialUpdateResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type environmentsSessionRecordingsPartialUpdateResponseSuccess =
    environmentsSessionRecordingsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingsPartialUpdateResponse =
    environmentsSessionRecordingsPartialUpdateResponseSuccess

export const getEnvironmentsSessionRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const environmentsSessionRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingsPartialUpdateResponse> => {
    return apiMutator<environmentsSessionRecordingsPartialUpdateResponse>(
        getEnvironmentsSessionRecordingsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedSessionRecordingApi),
        }
    )
}

export type environmentsSessionRecordingsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsSessionRecordingsDestroyResponseSuccess = environmentsSessionRecordingsDestroyResponse204 & {
    headers: Headers
}
export type environmentsSessionRecordingsDestroyResponse = environmentsSessionRecordingsDestroyResponseSuccess

export const getEnvironmentsSessionRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const environmentsSessionRecordingsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingsDestroyResponse> => {
    return apiMutator<environmentsSessionRecordingsDestroyResponse>(
        getEnvironmentsSessionRecordingsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Override list to include synthetic playlists
 */
export type sessionRecordingPlaylistsListResponse200 = {
    data: PaginatedSessionRecordingPlaylistListApi
    status: 200
}

export type sessionRecordingPlaylistsListResponseSuccess = sessionRecordingPlaylistsListResponse200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsListResponse = sessionRecordingPlaylistsListResponseSuccess

export const getSessionRecordingPlaylistsListUrl = (
    projectId: string,
    params?: SessionRecordingPlaylistsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/session_recording_playlists/?${stringifiedParams}`
        : `/api/projects/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsList = async (
    projectId: string,
    params?: SessionRecordingPlaylistsListParams,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsListResponse> => {
    return apiMutator<sessionRecordingPlaylistsListResponse>(getSessionRecordingPlaylistsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingPlaylistsCreateResponse201 = {
    data: SessionRecordingPlaylistApi
    status: 201
}

export type sessionRecordingPlaylistsCreateResponseSuccess = sessionRecordingPlaylistsCreateResponse201 & {
    headers: Headers
}
export type sessionRecordingPlaylistsCreateResponse = sessionRecordingPlaylistsCreateResponseSuccess

export const getSessionRecordingPlaylistsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsCreate = async (
    projectId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsCreateResponse> => {
    return apiMutator<sessionRecordingPlaylistsCreateResponse>(getSessionRecordingPlaylistsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export type sessionRecordingPlaylistsRetrieveResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsRetrieveResponseSuccess = sessionRecordingPlaylistsRetrieveResponse200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsRetrieveResponse = sessionRecordingPlaylistsRetrieveResponseSuccess

export const getSessionRecordingPlaylistsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRetrieveResponse> => {
    return apiMutator<sessionRecordingPlaylistsRetrieveResponse>(
        getSessionRecordingPlaylistsRetrieveUrl(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type sessionRecordingPlaylistsUpdateResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsUpdateResponseSuccess = sessionRecordingPlaylistsUpdateResponse200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsUpdateResponse = sessionRecordingPlaylistsUpdateResponseSuccess

export const getSessionRecordingPlaylistsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsUpdate = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsUpdateResponse> => {
    return apiMutator<sessionRecordingPlaylistsUpdateResponse>(
        getSessionRecordingPlaylistsUpdateUrl(projectId, shortId),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type sessionRecordingPlaylistsPartialUpdateResponse200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsPartialUpdateResponseSuccess =
    sessionRecordingPlaylistsPartialUpdateResponse200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsPartialUpdateResponse = sessionRecordingPlaylistsPartialUpdateResponseSuccess

export const getSessionRecordingPlaylistsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsPartialUpdateResponse> => {
    return apiMutator<sessionRecordingPlaylistsPartialUpdateResponse>(
        getSessionRecordingPlaylistsPartialUpdateUrl(projectId, shortId),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedSessionRecordingPlaylistApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type sessionRecordingPlaylistsDestroyResponse405 = {
    data: void
    status: 405
}
export type sessionRecordingPlaylistsDestroyResponseError = sessionRecordingPlaylistsDestroyResponse405 & {
    headers: Headers
}

export type sessionRecordingPlaylistsDestroyResponse = sessionRecordingPlaylistsDestroyResponseError

export const getSessionRecordingPlaylistsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsDestroyResponse> => {
    return apiMutator<sessionRecordingPlaylistsDestroyResponse>(
        getSessionRecordingPlaylistsDestroyUrl(projectId, shortId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingPlaylistsRecordingsRetrieveResponse200 = {
    data: void
    status: 200
}

export type sessionRecordingPlaylistsRecordingsRetrieveResponseSuccess =
    sessionRecordingPlaylistsRecordingsRetrieveResponse200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsRetrieveResponse =
    sessionRecordingPlaylistsRecordingsRetrieveResponseSuccess

export const getSessionRecordingPlaylistsRecordingsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const sessionRecordingPlaylistsRecordingsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsRetrieveResponse> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsRetrieveResponse>(
        getSessionRecordingPlaylistsRecordingsRetrieveUrl(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type sessionRecordingPlaylistsRecordingsCreateResponse200 = {
    data: void
    status: 200
}

export type sessionRecordingPlaylistsRecordingsCreateResponseSuccess =
    sessionRecordingPlaylistsRecordingsCreateResponse200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsCreateResponse = sessionRecordingPlaylistsRecordingsCreateResponseSuccess

export const getSessionRecordingPlaylistsRecordingsCreateUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsCreate = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsCreateResponse> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsCreateResponse>(
        getSessionRecordingPlaylistsRecordingsCreateUrl(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type sessionRecordingPlaylistsRecordingsDestroyResponse204 = {
    data: void
    status: 204
}

export type sessionRecordingPlaylistsRecordingsDestroyResponseSuccess =
    sessionRecordingPlaylistsRecordingsDestroyResponse204 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsDestroyResponse =
    sessionRecordingPlaylistsRecordingsDestroyResponseSuccess

export const getSessionRecordingPlaylistsRecordingsDestroyUrl = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsDestroy = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsDestroyResponse> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsDestroyResponse>(
        getSessionRecordingPlaylistsRecordingsDestroyUrl(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingsListResponse200 = {
    data: PaginatedSessionRecordingListApi
    status: 200
}

export type sessionRecordingsListResponseSuccess = sessionRecordingsListResponse200 & {
    headers: Headers
}
export type sessionRecordingsListResponse = sessionRecordingsListResponseSuccess

export const getSessionRecordingsListUrl = (projectId: string, params?: SessionRecordingsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/session_recordings/?${stringifiedParams}`
        : `/api/projects/${projectId}/session_recordings/`
}

export const sessionRecordingsList = async (
    projectId: string,
    params?: SessionRecordingsListParams,
    options?: RequestInit
): Promise<sessionRecordingsListResponse> => {
    return apiMutator<sessionRecordingsListResponse>(getSessionRecordingsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingsRetrieveResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsRetrieveResponseSuccess = sessionRecordingsRetrieveResponse200 & {
    headers: Headers
}
export type sessionRecordingsRetrieveResponse = sessionRecordingsRetrieveResponseSuccess

export const getSessionRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<sessionRecordingsRetrieveResponse> => {
    return apiMutator<sessionRecordingsRetrieveResponse>(getSessionRecordingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingsUpdateResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsUpdateResponseSuccess = sessionRecordingsUpdateResponse200 & {
    headers: Headers
}
export type sessionRecordingsUpdateResponse = sessionRecordingsUpdateResponseSuccess

export const getSessionRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsUpdate = async (
    projectId: string,
    id: string,
    sessionRecordingApi: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<sessionRecordingsUpdateResponse> => {
    return apiMutator<sessionRecordingsUpdateResponse>(getSessionRecordingsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingApi),
    })
}

export type sessionRecordingsPartialUpdateResponse200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsPartialUpdateResponseSuccess = sessionRecordingsPartialUpdateResponse200 & {
    headers: Headers
}
export type sessionRecordingsPartialUpdateResponse = sessionRecordingsPartialUpdateResponseSuccess

export const getSessionRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<sessionRecordingsPartialUpdateResponse> => {
    return apiMutator<sessionRecordingsPartialUpdateResponse>(getSessionRecordingsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingApi),
    })
}

export type sessionRecordingsDestroyResponse204 = {
    data: void
    status: 204
}

export type sessionRecordingsDestroyResponseSuccess = sessionRecordingsDestroyResponse204 & {
    headers: Headers
}
export type sessionRecordingsDestroyResponse = sessionRecordingsDestroyResponseSuccess

export const getSessionRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<sessionRecordingsDestroyResponse> => {
    return apiMutator<sessionRecordingsDestroyResponse>(getSessionRecordingsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
