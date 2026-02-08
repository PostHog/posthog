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
    DesktopRecordingsListParams,
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
export const getDesktopRecordingsListUrl = (projectId: string, params?: DesktopRecordingsListParams) => {
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

export const desktopRecordingsList = async (
    projectId: string,
    params?: DesktopRecordingsListParams,
    options?: RequestInit
): Promise<PaginatedDesktopRecordingListApi> => {
    return apiMutator<PaginatedDesktopRecordingListApi>(getDesktopRecordingsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new recording and get Recall.ai upload token for the desktop SDK
 */
export const getDesktopRecordingsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/desktop_recordings/`
}

export const desktopRecordingsCreate = async (
    projectId: string,
    createRecordingRequestApi: CreateRecordingRequestApi,
    options?: RequestInit
): Promise<CreateRecordingResponseApi> => {
    return apiMutator<CreateRecordingResponseApi>(getDesktopRecordingsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRecordingRequestApi),
    })
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const getDesktopRecordingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const desktopRecordingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DesktopRecordingApi> => {
    return apiMutator<DesktopRecordingApi>(getDesktopRecordingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const getDesktopRecordingsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const desktopRecordingsUpdate = async (
    projectId: string,
    id: string,
    desktopRecordingApi: NonReadonly<DesktopRecordingApi>,
    options?: RequestInit
): Promise<DesktopRecordingApi> => {
    return apiMutator<DesktopRecordingApi>(getDesktopRecordingsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(desktopRecordingApi),
    })
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const getDesktopRecordingsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const desktopRecordingsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDesktopRecordingApi: NonReadonly<PatchedDesktopRecordingApi>,
    options?: RequestInit
): Promise<DesktopRecordingApi> => {
    return apiMutator<DesktopRecordingApi>(getDesktopRecordingsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDesktopRecordingApi),
    })
}

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const getDesktopRecordingsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/`
}

export const desktopRecordingsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDesktopRecordingsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Append transcript segments (supports batched real-time streaming)
 */
export const getDesktopRecordingsAppendSegmentsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/desktop_recordings/${id}/append_segments/`
}

export const desktopRecordingsAppendSegmentsCreate = async (
    projectId: string,
    id: string,
    appendSegmentsApi: AppendSegmentsApi,
    options?: RequestInit
): Promise<DesktopRecordingApi> => {
    return apiMutator<DesktopRecordingApi>(getDesktopRecordingsAppendSegmentsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(appendSegmentsApi),
    })
}
