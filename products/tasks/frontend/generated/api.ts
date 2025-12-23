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
import type { PaginatedTaskListApi, PatchedTaskApi, TaskApi, TasksListParams } from './api.schemas'

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
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, and repository.
 * @summary List tasks
 */
export type tasksListResponse200 = {
    data: PaginatedTaskListApi
    status: 200
}

export type tasksListResponseSuccess = tasksListResponse200 & {
    headers: Headers
}
export type tasksListResponse = tasksListResponseSuccess

export const getTasksListUrl = (projectId: string, params?: TasksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/`
}

export const tasksList = async (
    projectId: string,
    params?: TasksListParams,
    options?: RequestInit
): Promise<tasksListResponse> => {
    return apiMutator<tasksListResponse>(getTasksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export type tasksCreateResponse201 = {
    data: TaskApi
    status: 201
}

export type tasksCreateResponseSuccess = tasksCreateResponse201 & {
    headers: Headers
}
export type tasksCreateResponse = tasksCreateResponseSuccess

export const getTasksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/`
}

export const tasksCreate = async (
    projectId: string,
    taskApi: TaskApi,
    options?: RequestInit
): Promise<tasksCreateResponse> => {
    return apiMutator<tasksCreateResponse>(getTasksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export type tasksRetrieveResponse200 = {
    data: TaskApi
    status: 200
}

export type tasksRetrieveResponseSuccess = tasksRetrieveResponse200 & {
    headers: Headers
}
export type tasksRetrieveResponse = tasksRetrieveResponseSuccess

export const getTasksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<tasksRetrieveResponse> => {
    return apiMutator<tasksRetrieveResponse>(getTasksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export type tasksUpdateResponse200 = {
    data: TaskApi
    status: 200
}

export type tasksUpdateResponseSuccess = tasksUpdateResponse200 & {
    headers: Headers
}
export type tasksUpdateResponse = tasksUpdateResponseSuccess

export const getTasksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksUpdate = async (
    projectId: string,
    id: string,
    taskApi: TaskApi,
    options?: RequestInit
): Promise<tasksUpdateResponse> => {
    return apiMutator<tasksUpdateResponse>(getTasksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export type tasksPartialUpdateResponse200 = {
    data: TaskApi
    status: 200
}

export type tasksPartialUpdateResponseSuccess = tasksPartialUpdateResponse200 & {
    headers: Headers
}
export type tasksPartialUpdateResponse = tasksPartialUpdateResponseSuccess

export const getTasksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTaskApi: NonReadonly<PatchedTaskApi>,
    options?: RequestInit
): Promise<tasksPartialUpdateResponse> => {
    return apiMutator<tasksPartialUpdateResponse>(getTasksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export type tasksDestroyResponse204 = {
    data: void
    status: 204
}

export type tasksDestroyResponseSuccess = tasksDestroyResponse204 & {
    headers: Headers
}
export type tasksDestroyResponse = tasksDestroyResponseSuccess

export const getTasksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<tasksDestroyResponse> => {
    return apiMutator<tasksDestroyResponse>(getTasksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export type tasksRunCreateResponse200 = {
    data: TaskApi
    status: 200
}

export type tasksRunCreateResponse404 = {
    data: void
    status: 404
}

export type tasksRunCreateResponseSuccess = tasksRunCreateResponse200 & {
    headers: Headers
}
export type tasksRunCreateResponseError = tasksRunCreateResponse404 & {
    headers: Headers
}

export type tasksRunCreateResponse = tasksRunCreateResponseSuccess | tasksRunCreateResponseError

export const getTasksRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/run/`
}

export const tasksRunCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<tasksRunCreateResponse> => {
    return apiMutator<tasksRunCreateResponse>(getTasksRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}
