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
): Promise<PaginatedSessionRecordingPlaylistListApi> => {
    return apiMutator<PaginatedSessionRecordingPlaylistListApi>(
        getSessionRecordingPlaylistsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSessionRecordingPlaylistsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsCreate = async (
    projectId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingPlaylistsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsUpdate = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingPlaylistApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getSessionRecordingPlaylistsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getSessionRecordingPlaylistsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingPlaylistsRecordingsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const sessionRecordingPlaylistsRecordingsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsCreateUrl(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsDestroyUrl(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedSessionRecordingListApi> => {
    return apiMutator<PaginatedSessionRecordingListApi>(getSessionRecordingsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsUpdate = async (
    projectId: string,
    id: string,
    sessionRecordingApi: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingApi),
    })
}

export const getSessionRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingApi),
    })
}

export const getSessionRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSessionRecordingsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Override list to include synthetic playlists
 */
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
): Promise<PaginatedSessionRecordingPlaylistListApi> => {
    return apiMutator<PaginatedSessionRecordingPlaylistListApi>(
        getSessionRecordingPlaylistsList2Url(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSessionRecordingPlaylistsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/`
}

export const sessionRecordingPlaylistsCreate2 = async (
    projectId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsRetrieve2Url(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingPlaylistsUpdate2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsUpdate2 = async (
    projectId: string,
    shortId: string,
    sessionRecordingPlaylistApi: NonReadonly<SessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsUpdate2Url(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

export const getSessionRecordingPlaylistsPartialUpdate2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsPartialUpdate2 = async (
    projectId: string,
    shortId: string,
    patchedSessionRecordingPlaylistApi: NonReadonly<PatchedSessionRecordingPlaylistApi>,
    options?: RequestInit
): Promise<SessionRecordingPlaylistApi> => {
    return apiMutator<SessionRecordingPlaylistApi>(getSessionRecordingPlaylistsPartialUpdate2Url(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingPlaylistApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getSessionRecordingPlaylistsDestroy2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/`
}

export const sessionRecordingPlaylistsDestroy2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getSessionRecordingPlaylistsDestroy2Url(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingPlaylistsRecordingsRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/session_recording_playlists/${shortId}/recordings/`
}

export const sessionRecordingPlaylistsRecordingsRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsRetrieve2Url(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsCreate2Url(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingPlaylistApi),
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingPlaylistsRecordingsDestroy2Url(projectId, shortId, sessionRecordingId), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedSessionRecordingListApi> => {
    return apiMutator<PaginatedSessionRecordingListApi>(getSessionRecordingsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSessionRecordingsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsUpdate2 = async (
    projectId: string,
    id: string,
    sessionRecordingApi: NonReadonly<SessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionRecordingApi),
    })
}

export const getSessionRecordingsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedSessionRecordingApi: NonReadonly<PatchedSessionRecordingApi>,
    options?: RequestInit
): Promise<SessionRecordingApi> => {
    return apiMutator<SessionRecordingApi>(getSessionRecordingsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSessionRecordingApi),
    })
}

export const getSessionRecordingsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/session_recordings/${id}/`
}

export const sessionRecordingsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
