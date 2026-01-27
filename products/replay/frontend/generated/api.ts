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
    PaginatedSessionRecordingListApi,
    PaginatedSessionRecordingPlaylistListApi,
    PatchedSessionRecordingApi,
    PatchedSessionRecordingPlaylistApi,
    SessionRecordingApi,
    SessionRecordingPlaylistApi,
    SessionRecordingPlaylistsList2Params,
    SessionRecordingPlaylistsListParams,
    SessionRecordingsList2Params,
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
        ? `/api/environments/${projectId}/session_recording_playlists/?${stringifiedParams}`
        : `/api/environments/${projectId}/session_recording_playlists/`
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
    return `/api/environments/${projectId}/session_recording_playlists/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
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
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
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
        ? `/api/environments/${projectId}/session_recordings/?${stringifiedParams}`
        : `/api/environments/${projectId}/session_recordings/`
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
    return `/api/environments/${projectId}/session_recordings/${id}/`
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
    return `/api/environments/${projectId}/session_recordings/${id}/`
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
    return `/api/environments/${projectId}/session_recordings/${id}/`
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
    return `/api/environments/${projectId}/session_recordings/${id}/`
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

/**
 * Override list to include synthetic playlists
 */
export type sessionRecordingPlaylistsList2Response200 = {
    data: PaginatedSessionRecordingPlaylistListApi
    status: 200
}

export type sessionRecordingPlaylistsList2ResponseSuccess = sessionRecordingPlaylistsList2Response200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsList2Response = sessionRecordingPlaylistsList2ResponseSuccess

export const getSessionRecordingPlaylistsList2Url = (
    projectId: string,
    params?: SessionRecordingPlaylistsList2Params
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

export const sessionRecordingPlaylistsList2 = async (
    projectId: string,
    params?: SessionRecordingPlaylistsList2Params,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsList2Response> => {
    return apiMutator<sessionRecordingPlaylistsList2Response>(getSessionRecordingPlaylistsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingPlaylistsCreate2Response201 = {
    data: SessionRecordingPlaylistApi
    status: 201
}

export type sessionRecordingPlaylistsCreate2ResponseSuccess = sessionRecordingPlaylistsCreate2Response201 & {
    headers: Headers
}
export type sessionRecordingPlaylistsCreate2Response = sessionRecordingPlaylistsCreate2ResponseSuccess

export const getSessionRecordingPlaylistsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsCreate2 = async (
    projectId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsCreate2Response> => {
    return apiMutator<sessionRecordingPlaylistsCreate2Response>(getSessionRecordingPlaylistsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export type sessionRecordingPlaylistsRetrieve2Response200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsRetrieve2ResponseSuccess = sessionRecordingPlaylistsRetrieve2Response200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsRetrieve2Response = sessionRecordingPlaylistsRetrieve2ResponseSuccess

export const getSessionRecordingPlaylistsRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRetrieve2Response> => {
    return apiMutator<sessionRecordingPlaylistsRetrieve2Response>(
        getSessionRecordingPlaylistsRetrieve2Url(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type sessionRecordingPlaylistsUpdate2Response200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsUpdate2ResponseSuccess = sessionRecordingPlaylistsUpdate2Response200 & {
    headers: Headers
}
export type sessionRecordingPlaylistsUpdate2Response = sessionRecordingPlaylistsUpdate2ResponseSuccess

export const getSessionRecordingPlaylistsUpdate2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsUpdate2 = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsUpdate2Response> => {
    return apiMutator<sessionRecordingPlaylistsUpdate2Response>(
        getSessionRecordingPlaylistsUpdate2Url(projectId, shortId),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type sessionRecordingPlaylistsPartialUpdate2Response200 = {
    data: SessionRecordingPlaylistApi
    status: 200
}

export type sessionRecordingPlaylistsPartialUpdate2ResponseSuccess =
    sessionRecordingPlaylistsPartialUpdate2Response200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsPartialUpdate2Response = sessionRecordingPlaylistsPartialUpdate2ResponseSuccess

export const getSessionRecordingPlaylistsPartialUpdate2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsPartialUpdate2 = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsPartialUpdate2Response> => {
    return apiMutator<sessionRecordingPlaylistsPartialUpdate2Response>(
        getSessionRecordingPlaylistsPartialUpdate2Url(projectId, shortId),
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
export type sessionRecordingPlaylistsDestroy2Response405 = {
    data: void
    status: 405
}
export type sessionRecordingPlaylistsDestroy2ResponseError = sessionRecordingPlaylistsDestroy2Response405 & {
    headers: Headers
}

export type sessionRecordingPlaylistsDestroy2Response = sessionRecordingPlaylistsDestroy2ResponseError

export const getSessionRecordingPlaylistsDestroy2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsDestroy2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsDestroy2Response> => {
    return apiMutator<sessionRecordingPlaylistsDestroy2Response>(
        getSessionRecordingPlaylistsDestroy2Url(projectId, shortId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingPlaylistsRecordingsRetrieve2Response200 = {
    data: void
    status: 200
}

export type sessionRecordingPlaylistsRecordingsRetrieve2ResponseSuccess =
    sessionRecordingPlaylistsRecordingsRetrieve2Response200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsRetrieve2Response =
    sessionRecordingPlaylistsRecordingsRetrieve2ResponseSuccess

export const getSessionRecordingPlaylistsRecordingsRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const sessionRecordingPlaylistsRecordingsRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsRetrieve2Response> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsRetrieve2Response>(
        getSessionRecordingPlaylistsRecordingsRetrieve2Url(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type sessionRecordingPlaylistsRecordingsCreate2Response200 = {
    data: void
    status: 200
}

export type sessionRecordingPlaylistsRecordingsCreate2ResponseSuccess =
    sessionRecordingPlaylistsRecordingsCreate2Response200 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsCreate2Response =
    sessionRecordingPlaylistsRecordingsCreate2ResponseSuccess

export const getSessionRecordingPlaylistsRecordingsCreate2Url = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsCreate2 = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsCreate2Response> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsCreate2Response>(
        getSessionRecordingPlaylistsRecordingsCreate2Url(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sessionRecordingPlaylistApi),
        }
    )
}

export type sessionRecordingPlaylistsRecordingsDestroy2Response204 = {
    data: void
    status: 204
}

export type sessionRecordingPlaylistsRecordingsDestroy2ResponseSuccess =
    sessionRecordingPlaylistsRecordingsDestroy2Response204 & {
        headers: Headers
    }
export type sessionRecordingPlaylistsRecordingsDestroy2Response =
    sessionRecordingPlaylistsRecordingsDestroy2ResponseSuccess

export const getSessionRecordingPlaylistsRecordingsDestroy2Url = (
    projectId: string,
    shortId: string,
    sessionRecordingId: string
) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/${sessionRecordingId}/`
}

export const sessionRecordingPlaylistsRecordingsDestroy2 = async (
    projectId: string,
    shortId: string,
    sessionRecordingId: string,
    options?: RequestInit
): Promise<sessionRecordingPlaylistsRecordingsDestroy2Response> => {
    return apiMutator<sessionRecordingPlaylistsRecordingsDestroy2Response>(
        getSessionRecordingPlaylistsRecordingsDestroy2Url(projectId, shortId, sessionRecordingId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingsList2Response200 = {
    data: PaginatedSessionRecordingListApi
    status: 200
}

export type sessionRecordingsList2ResponseSuccess = sessionRecordingsList2Response200 & {
    headers: Headers
}
export type sessionRecordingsList2Response = sessionRecordingsList2ResponseSuccess

export const getSessionRecordingsList2Url = (projectId: string, params?: SessionRecordingsList2Params) => {
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

export const sessionRecordingsList2 = async (
    projectId: string,
    params?: SessionRecordingsList2Params,
    options?: RequestInit
): Promise<sessionRecordingsList2Response> => {
    return apiMutator<sessionRecordingsList2Response>(getSessionRecordingsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingsRetrieve2Response200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsRetrieve2ResponseSuccess = sessionRecordingsRetrieve2Response200 & {
    headers: Headers
}
export type sessionRecordingsRetrieve2Response = sessionRecordingsRetrieve2ResponseSuccess

export const getSessionRecordingsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<sessionRecordingsRetrieve2Response> => {
    return apiMutator<sessionRecordingsRetrieve2Response>(getSessionRecordingsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type sessionRecordingsUpdate2Response200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsUpdate2ResponseSuccess = sessionRecordingsUpdate2Response200 & {
    headers: Headers
}
export type sessionRecordingsUpdate2Response = sessionRecordingsUpdate2ResponseSuccess

export const getSessionRecordingsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsUpdate2 = async (
    projectId: string,
    id: string,
    sessionRecordingApi: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<sessionRecordingsUpdate2Response> => {
    return apiMutator<sessionRecordingsUpdate2Response>(getSessionRecordingsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingApi),
    })
}

export type sessionRecordingsPartialUpdate2Response200 = {
    data: SessionRecordingApi
    status: 200
}

export type sessionRecordingsPartialUpdate2ResponseSuccess = sessionRecordingsPartialUpdate2Response200 & {
    headers: Headers
}
export type sessionRecordingsPartialUpdate2Response = sessionRecordingsPartialUpdate2ResponseSuccess

export const getSessionRecordingsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<sessionRecordingsPartialUpdate2Response> => {
    return apiMutator<sessionRecordingsPartialUpdate2Response>(getSessionRecordingsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingApi),
    })
}

export type sessionRecordingsDestroy2Response204 = {
    data: void
    status: 204
}

export type sessionRecordingsDestroy2ResponseSuccess = sessionRecordingsDestroy2Response204 & {
    headers: Headers
}
export type sessionRecordingsDestroy2Response = sessionRecordingsDestroy2ResponseSuccess

export const getSessionRecordingsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<sessionRecordingsDestroy2Response> => {
    return apiMutator<sessionRecordingsDestroy2Response>(getSessionRecordingsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
