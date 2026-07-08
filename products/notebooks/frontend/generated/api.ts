import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    NotebookApi,
    NotebookCollabPresenceApi,
    NotebookCollabSaveApi,
    NotebookMarkdownApi,
    NotebookMarkdownSaveApi,
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

export const getNotebooksListUrl = (projectId: string, params?: NotebooksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/notebooks/?${stringifiedParams}`
        : `/api/projects/${projectId}/notebooks/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
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

export const getNotebooksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCreate = async (
    projectId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
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

export const getNotebooksUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksUpdate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedNotebookApi?: NonReadonly<PatchedNotebookApi>,
    options?: RequestInit
): Promise<NotebookApi> => {
    return apiMutator<NotebookApi>(getNotebooksPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedNotebookApi),
    })
}

export const getNotebooksDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const notebooksDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getNotebooksDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getNotebooksActivityRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/activity/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksActivityRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksActivityRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getNotebooksCollabMarkdownSaveCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/collab/markdown_save/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabMarkdownSaveCreate = async (
    projectId: string,
    shortId: string,
    notebookMarkdownSaveApi: NotebookMarkdownSaveApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksCollabMarkdownSaveCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookMarkdownSaveApi),
    })
}

export const getNotebooksCollabPresenceCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/collab/presence/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabPresenceCreate = async (
    projectId: string,
    shortId: string,
    notebookCollabPresenceApi: NotebookCollabPresenceApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksCollabPresenceCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookCollabPresenceApi),
    })
}

export const getNotebooksCollabSaveCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/collab/save/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabSaveCreate = async (
    projectId: string,
    shortId: string,
    notebookCollabSaveApi: NotebookCollabSaveApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksCollabSaveCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookCollabSaveApi),
    })
}

export const getNotebooksCollabStreamRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/collab/stream/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksCollabStreamRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksCollabStreamRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getNotebooksHogqlExecuteCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/hogql/execute/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksHogqlExecuteCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksHogqlExecuteCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelConfigCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/config/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelConfigCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelConfigCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelDataframeRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/dataframe/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
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

export const getNotebooksKernelExecuteCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/execute/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelExecuteCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelExecuteStreamCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/execute/stream/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelExecuteStreamCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelExecuteStreamCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelRestartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/restart/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelRestartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelRestartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelStartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/start/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStartCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelStartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksKernelStatusRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/status/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
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

export const getNotebooksKernelStopCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/kernel/stop/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksKernelStopCreate = async (
    projectId: string,
    shortId: string,
    notebookApi?: NonReadonly<NotebookApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksKernelStopCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(notebookApi),
    })
}

export const getNotebooksMarkdownRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/notebooks/${shortId}/markdown/`
}

/**
 * Return the notebook's content rendered as markdown. Markdown notebooks return their stored markdown source; legacy rich-text notebooks are converted from their ProseMirror document. Useful for exporting a notebook into docs or feeding it to an AI agent.
 */
export const notebooksMarkdownRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<NotebookMarkdownApi> => {
    return apiMutator<NotebookMarkdownApi>(getNotebooksMarkdownRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getNotebooksAllActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/activity/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksAllActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotebooksAllActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getNotebooksRecordingCommentsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/notebooks/recording_comments/`
}

/**
 * The API for interacting with Notebooks. This feature is in early access and the API can have breaking changes without announcement.
 */
export const notebooksRecordingCommentsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getNotebooksRecordingCommentsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
