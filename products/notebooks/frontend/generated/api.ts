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
    NotebookApi,
    NotebooksListParams,
    PaginatedNotebookMinimalListApi,
    PatchedNotebookApi,
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
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksListResponse200 = {
    data: PaginatedNotebookMinimalListApi
    status: 200
}

export type notebooksListResponseSuccess = notebooksListResponse200 & {
    headers: Headers
}
export type notebooksListResponse = notebooksListResponseSuccess

export const getNotebooksListUrl = (projectId: string, params?: NotebooksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/notebooks/?${stringifiedParams}`
        : `/api/projects/${projectId}/notebooks/`
}

export const notebooksList = async (
    projectId: string,
    params?: NotebooksListParams,
    options?: RequestInit
): Promise<notebooksListResponse> => {
    return apiMutator<notebooksListResponse>(getNotebooksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksCreateResponse201 = {
    data: NotebookApi
    status: 201
}

export type notebooksCreateResponseSuccess = notebooksCreateResponse201 & {
    headers: Headers
}
export type notebooksCreateResponse = notebooksCreateResponseSuccess

export const getNotebooksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/`
}

export const notebooksCreate = async (
    projectId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksCreateResponse> => {
    return apiMutator<notebooksCreateResponse>(getNotebooksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksRetrieveResponse200 = {
    data: NotebookApi
    status: 200
}

export type notebooksRetrieveResponseSuccess = notebooksRetrieveResponse200 & {
    headers: Headers
}
export type notebooksRetrieveResponse = notebooksRetrieveResponseSuccess

export const getNotebooksRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<notebooksRetrieveResponse> => {
    return apiMutator<notebooksRetrieveResponse>(getNotebooksRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksUpdateResponse200 = {
    data: NotebookApi
    status: 200
}

export type notebooksUpdateResponseSuccess = notebooksUpdateResponse200 & {
    headers: Headers
}
export type notebooksUpdateResponse = notebooksUpdateResponseSuccess

export const getNotebooksUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksUpdate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksUpdateResponse> => {
    return apiMutator<notebooksUpdateResponse>(getNotebooksUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksPartialUpdateResponse200 = {
    data: NotebookApi
    status: 200
}

export type notebooksPartialUpdateResponseSuccess = notebooksPartialUpdateResponse200 & {
    headers: Headers
}
export type notebooksPartialUpdateResponse = notebooksPartialUpdateResponseSuccess

export const getNotebooksPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedNotebookApi: NonReadonly<PatchedNotebookApi>,
    options?: RequestInit
): Promise<notebooksPartialUpdateResponse> => {
    return apiMutator<notebooksPartialUpdateResponse>(getNotebooksPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedNotebookApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type notebooksDestroyResponse405 = {
    data: void
    status: 405
}
export type notebooksDestroyResponseError = notebooksDestroyResponse405 & {
    headers: Headers
}

export type notebooksDestroyResponse = notebooksDestroyResponseError

export const getNotebooksDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<notebooksDestroyResponse> => {
    return apiMutator<notebooksDestroyResponse>(getNotebooksDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type notebooksActivityRetrieve2ResponseSuccess = notebooksActivityRetrieve2Response200 & {
    headers: Headers
}
export type notebooksActivityRetrieve2Response = notebooksActivityRetrieve2ResponseSuccess

export const getNotebooksActivityRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/activity/`
}

export const notebooksActivityRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<notebooksActivityRetrieve2Response> => {
    return apiMutator<notebooksActivityRetrieve2Response>(getNotebooksActivityRetrieve2Url(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelConfigCreateResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelConfigCreateResponseSuccess = notebooksKernelConfigCreateResponse200 & {
    headers: Headers
}
export type notebooksKernelConfigCreateResponse = notebooksKernelConfigCreateResponseSuccess

export const getNotebooksKernelConfigCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/config/`
}

export const notebooksKernelConfigCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksKernelConfigCreateResponse> => {
    return apiMutator<notebooksKernelConfigCreateResponse>(getNotebooksKernelConfigCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelDataframeRetrieveResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelDataframeRetrieveResponseSuccess = notebooksKernelDataframeRetrieveResponse200 & {
    headers: Headers
}
export type notebooksKernelDataframeRetrieveResponse = notebooksKernelDataframeRetrieveResponseSuccess

export const getNotebooksKernelDataframeRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/dataframe/`
}

export const notebooksKernelDataframeRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<notebooksKernelDataframeRetrieveResponse> => {
    return apiMutator<notebooksKernelDataframeRetrieveResponse>(
        getNotebooksKernelDataframeRetrieveUrl(projectId, shortId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelExecuteCreateResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelExecuteCreateResponseSuccess = notebooksKernelExecuteCreateResponse200 & {
    headers: Headers
}
export type notebooksKernelExecuteCreateResponse = notebooksKernelExecuteCreateResponseSuccess

export const getNotebooksKernelExecuteCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/execute/`
}

export const notebooksKernelExecuteCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksKernelExecuteCreateResponse> => {
    return apiMutator<notebooksKernelExecuteCreateResponse>(getNotebooksKernelExecuteCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelRestartCreateResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelRestartCreateResponseSuccess = notebooksKernelRestartCreateResponse200 & {
    headers: Headers
}
export type notebooksKernelRestartCreateResponse = notebooksKernelRestartCreateResponseSuccess

export const getNotebooksKernelRestartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/restart/`
}

export const notebooksKernelRestartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksKernelRestartCreateResponse> => {
    return apiMutator<notebooksKernelRestartCreateResponse>(getNotebooksKernelRestartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelStartCreateResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelStartCreateResponseSuccess = notebooksKernelStartCreateResponse200 & {
    headers: Headers
}
export type notebooksKernelStartCreateResponse = notebooksKernelStartCreateResponseSuccess

export const getNotebooksKernelStartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/start/`
}

export const notebooksKernelStartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksKernelStartCreateResponse> => {
    return apiMutator<notebooksKernelStartCreateResponse>(getNotebooksKernelStartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelStatusRetrieveResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelStatusRetrieveResponseSuccess = notebooksKernelStatusRetrieveResponse200 & {
    headers: Headers
}
export type notebooksKernelStatusRetrieveResponse = notebooksKernelStatusRetrieveResponseSuccess

export const getNotebooksKernelStatusRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/status/`
}

export const notebooksKernelStatusRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<notebooksKernelStatusRetrieveResponse> => {
    return apiMutator<notebooksKernelStatusRetrieveResponse>(getNotebooksKernelStatusRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksKernelStopCreateResponse200 = {
    data: void
    status: 200
}

export type notebooksKernelStopCreateResponseSuccess = notebooksKernelStopCreateResponse200 & {
    headers: Headers
}
export type notebooksKernelStopCreateResponse = notebooksKernelStopCreateResponseSuccess

export const getNotebooksKernelStopCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/stop/`
}

export const notebooksKernelStopCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<notebooksKernelStopCreateResponse> => {
    return apiMutator<notebooksKernelStopCreateResponse>(getNotebooksKernelStopCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type notebooksActivityRetrieveResponseSuccess = notebooksActivityRetrieveResponse200 & {
    headers: Headers
}
export type notebooksActivityRetrieveResponse = notebooksActivityRetrieveResponseSuccess

export const getNotebooksActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/activity/`
}

export const notebooksActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<notebooksActivityRetrieveResponse> => {
    return apiMutator<notebooksActivityRetrieveResponse>(getNotebooksActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export type notebooksRecordingCommentsRetrieveResponse200 = {
    data: void
    status: 200
}

export type notebooksRecordingCommentsRetrieveResponseSuccess = notebooksRecordingCommentsRetrieveResponse200 & {
    headers: Headers
}
export type notebooksRecordingCommentsRetrieveResponse = notebooksRecordingCommentsRetrieveResponseSuccess

export const getNotebooksRecordingCommentsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/recording_comments/`
}

export const notebooksRecordingCommentsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<notebooksRecordingCommentsRetrieveResponse> => {
    return apiMutator<notebooksRecordingCommentsRetrieveResponse>(getNotebooksRecordingCommentsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
