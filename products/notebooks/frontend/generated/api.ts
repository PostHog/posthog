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
): Promise<PaginatedNotebookMinimalListApi> => {
    return apiMutator<PaginatedNotebookMinimalListApi>(getNotebooksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/`
}

export const notebooksCreate = async (
    projectId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksUpdate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedNotebookApi: NonReadonly<PatchedNotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedNotebookApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getNotebooksDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

export const notebooksDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getNotebooksDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksActivityRetrieve2Url = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/activity/`
}

export const notebooksActivityRetrieve2 = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksActivityRetrieve2Url(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelConfigCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/config/`
}

export const notebooksKernelConfigCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelConfigCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelDataframeRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/dataframe/`
}

export const notebooksKernelDataframeRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelDataframeRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelExecuteCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/execute/`
}

export const notebooksKernelExecuteCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelExecuteCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelRestartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/restart/`
}

export const notebooksKernelRestartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelRestartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelStartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/start/`
}

export const notebooksKernelStartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelStartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelStatusRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/status/`
}

export const notebooksKernelStatusRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelStatusRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksKernelStopCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/stop/`
}

export const notebooksKernelStopCreate = async (
    projectId: string,
    shortId: string,
    notebookApi: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelStopCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/activity/`
}

export const notebooksActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotebooksActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const getNotebooksRecordingCommentsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/recording_comments/`
}

export const notebooksRecordingCommentsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotebooksRecordingCommentsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
