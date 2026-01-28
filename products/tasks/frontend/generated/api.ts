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
    PaginatedTaskListApi,
    PaginatedTaskRunDetailListApi,
    PatchedTaskApi,
    PatchedTaskRunUpdateApi,
    TaskApi,
    TaskRunAppendLogRequestApi,
    TaskRunArtifactPresignRequestApi,
    TaskRunArtifactPresignResponseApi,
    TaskRunArtifactsUploadRequestApi,
    TaskRunArtifactsUploadResponseApi,
    TaskRunDetailApi,
    TasksListParams,
    TasksRunsListParams,
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
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.
 * @summary List tasks
 */
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
): Promise<PaginatedTaskListApi> => {
    return apiMutator<PaginatedTaskListApi>(getTasksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const getTasksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/`
}

export const tasksCreate = async (projectId: string, taskApi: TaskApi, options?: RequestInit): Promise<TaskApi> => {
    return apiMutator<TaskApi>(getTasksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const getTasksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<TaskApi> => {
    return apiMutator<TaskApi>(getTasksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const getTasksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksUpdate = async (
    projectId: string,
    id: string,
    taskApi: TaskApi,
    options?: RequestInit
): Promise<TaskApi> => {
    return apiMutator<TaskApi>(getTasksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const getTasksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTaskApi: NonReadonly<PatchedTaskApi>,
    options?: RequestInit
): Promise<TaskApi> => {
    return apiMutator<TaskApi>(getTasksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskApi),
    })
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const getTasksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

export const tasksDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTasksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const getTasksRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/run/`
}

export const tasksRunCreate = async (projectId: string, id: string, options?: RequestInit): Promise<TaskApi> => {
    return apiMutator<TaskApi>(getTasksRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * Get a list of runs for a specific task.
 * @summary List task runs
 */
export const getTasksRunsListUrl = (projectId: string, taskId: string, params?: TasksRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${taskId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${taskId}/runs/`
}

export const tasksRunsList = async (
    projectId: string,
    taskId: string,
    params?: TasksRunsListParams,
    options?: RequestInit
): Promise<PaginatedTaskRunDetailListApi> => {
    return apiMutator<PaginatedTaskRunDetailListApi>(getTasksRunsListUrl(projectId, taskId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new run for a specific task.
 * @summary Create task run
 */
export const getTasksRunsCreateUrl = (projectId: string, taskId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/`
}

export const tasksRunsCreate = async (
    projectId: string,
    taskId: string,
    options?: RequestInit
): Promise<TaskRunDetailApi> => {
    return apiMutator<TaskRunDetailApi>(getTasksRunsCreateUrl(projectId, taskId), {
        ...options,
        method: 'POST',
    })
}

/**
 * API for managing task runs. Each run represents an execution of a task.
 */
export const getTasksRunsRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/`
}

export const tasksRunsRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunDetailApi> => {
    return apiMutator<TaskRunDetailApi>(getTasksRunsRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Update task run
 */
export const getTasksRunsPartialUpdateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/`
}

export const tasksRunsPartialUpdate = async (
    projectId: string,
    taskId: string,
    id: string,
    patchedTaskRunUpdateApi: PatchedTaskRunUpdateApi,
    options?: RequestInit
): Promise<TaskRunDetailApi> => {
    return apiMutator<TaskRunDetailApi>(getTasksRunsPartialUpdateUrl(projectId, taskId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskRunUpdateApi),
    })
}

/**
 * Append one or more log entries to the task run log array
 * @summary Append log entries
 */
export const getTasksRunsAppendLogCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/append_log/`
}

export const tasksRunsAppendLogCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunAppendLogRequestApi: TaskRunAppendLogRequestApi,
    options?: RequestInit
): Promise<TaskRunDetailApi> => {
    return apiMutator<TaskRunDetailApi>(getTasksRunsAppendLogCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunAppendLogRequestApi),
    })
}

/**
 * Persist task artifacts to S3 and attach them to the run manifest.
 * @summary Upload artifacts for a task run
 */
export const getTasksRunsArtifactsCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/`
}

export const tasksRunsArtifactsCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactsUploadRequestApi: TaskRunArtifactsUploadRequestApi,
    options?: RequestInit
): Promise<TaskRunArtifactsUploadResponseApi> => {
    return apiMutator<TaskRunArtifactsUploadResponseApi>(getTasksRunsArtifactsCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunArtifactsUploadRequestApi),
    })
}

/**
 * Returns a temporary, signed URL that can be used to download a specific artifact.
 * @summary Generate presigned URL for an artifact
 */
export const getTasksRunsArtifactsPresignCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/presign/`
}

export const tasksRunsArtifactsPresignCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactPresignRequestApi: TaskRunArtifactPresignRequestApi,
    options?: RequestInit
): Promise<TaskRunArtifactPresignResponseApi> => {
    return apiMutator<TaskRunArtifactPresignResponseApi>(getTasksRunsArtifactsPresignCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunArtifactPresignRequestApi),
    })
}

/**
 * Update the output field for a task run (e.g., PR URL, commit SHA, etc.)
 * @summary Set run output
 */
export const getTasksRunsSetOutputPartialUpdateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/set_output/`
}

export const tasksRunsSetOutputPartialUpdate = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunDetailApi> => {
    return apiMutator<TaskRunDetailApi>(getTasksRunsSetOutputPartialUpdateUrl(projectId, taskId, id), {
        ...options,
        method: 'PATCH',
    })
}
