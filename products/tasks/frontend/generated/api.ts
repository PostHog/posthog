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
    ChannelDTOApi,
    ChannelWriteApi,
    CodeInviteRedeemRequestApi,
    ConnectionTokenResponseApi,
    PaginatedChannelDTOListApi,
    PaginatedSandboxEnvironmentDTOListApi,
    PaginatedTaskAutomationDTOListApi,
    PaginatedTaskDetailDTOListApi,
    PaginatedTaskRunDetailDTOListApi,
    PaginatedTaskSummaryDTOListApi,
    PaginatedTaskThreadMessageDTOListApi,
    PatchedChannelWriteApi,
    PatchedSandboxEnvironmentWriteApi,
    PatchedTaskAutomationWriteApi,
    PatchedTaskRunSetOutputRequestApi,
    PatchedTaskRunUpdateApi,
    PatchedTaskWriteApi,
    RepositoryReadinessResponseApi,
    SandboxEnvironmentDTOApi,
    SandboxEnvironmentWriteApi,
    SandboxListParams,
    SlackThreadContextResponseApi,
    StreamReadTokenResponseApi,
    TaskAutomationDTOApi,
    TaskAutomationWriteApi,
    TaskAutomationsListParams,
    TaskChannelsListParams,
    TaskDetailDTOApi,
    TaskPresenceBeaconRequestApi,
    TaskRepositoriesResponseApi,
    TaskRunAppendLogRequestApi,
    TaskRunArtifactPresignRequestApi,
    TaskRunArtifactPresignResponseApi,
    TaskRunArtifactsFinalizeUploadRequestApi,
    TaskRunArtifactsFinalizeUploadResponseApi,
    TaskRunArtifactsPrepareUploadRequestApi,
    TaskRunArtifactsPrepareUploadResponseApi,
    TaskRunArtifactsUploadRequestApi,
    TaskRunArtifactsUploadResponseApi,
    TaskRunBootstrapCreateRequestApi,
    TaskRunCommandRequestApi,
    TaskRunCommandResponseApi,
    TaskRunCreateRequestSchemaApi,
    TaskRunDetailDTOApi,
    TaskRunRelayMessageRequestApi,
    TaskRunRelayMessageResponseApi,
    TaskRunStartRequestApi,
    TaskStagedArtifactsFinalizeUploadRequestApi,
    TaskStagedArtifactsFinalizeUploadResponseApi,
    TaskStagedArtifactsPrepareUploadRequestApi,
    TaskStagedArtifactsPrepareUploadResponseApi,
    TaskSummariesRequestApi,
    TaskThreadMessageDTOApi,
    TaskThreadMessageWriteApi,
    TaskWriteApi,
    TasksListParams,
    TasksRepositoryReadinessRetrieveParams,
    TasksRunsListParams,
    TasksRunsSessionLogsRetrieveParams,
    TasksRunsStreamRetrieveParams,
    TasksSlackThreadContextRetrieveParams,
    TasksSummariesCreateParams,
    TasksThreadMessagesListParams,
    WarmTaskRequestApi,
    WarmTaskResponseApi,
} from './api.schemas'

export const getCodeInvitesCheckAccessRetrieveUrl = () => {
    return `/api/code/invites/check-access/`
}

/**
 * Check whether the authenticated user has access to PostHog Code.
 * @summary Check access
 */
export const codeInvitesCheckAccessRetrieve = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCodeInvitesCheckAccessRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getCodeInvitesRedeemCreateUrl = () => {
    return `/api/code/invites/redeem/`
}

/**
 * Redeem a PostHog Code invite code to enable access.
 * @summary Redeem invite code
 */
export const codeInvitesRedeemCreate = async (
    codeInviteRedeemRequestApi: CodeInviteRedeemRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCodeInvitesRedeemCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(codeInviteRedeemRequestApi),
    })
}

export const getSandboxListUrl = (projectId: string, params?: SandboxListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/sandbox_environments/?${stringifiedParams}`
        : `/api/projects/${projectId}/sandbox_environments/`
}

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxList = async (
    projectId: string,
    params?: SandboxListParams,
    options?: RequestInit
): Promise<PaginatedSandboxEnvironmentDTOListApi> => {
    return apiMutator<PaginatedSandboxEnvironmentDTOListApi>(getSandboxListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSandboxCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/sandbox_environments/`
}

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxCreate = async (
    projectId: string,
    sandboxEnvironmentWriteApi: SandboxEnvironmentWriteApi,
    options?: RequestInit
): Promise<SandboxEnvironmentDTOApi> => {
    return apiMutator<SandboxEnvironmentDTOApi>(getSandboxCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxEnvironmentWriteApi),
    })
}

export const getSandboxRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_environments/${id}/`
}

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SandboxEnvironmentDTOApi> => {
    return apiMutator<SandboxEnvironmentDTOApi>(getSandboxRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSandboxPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_environments/${id}/`
}

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSandboxEnvironmentWriteApi?: PatchedSandboxEnvironmentWriteApi,
    options?: RequestInit
): Promise<SandboxEnvironmentDTOApi> => {
    return apiMutator<SandboxEnvironmentDTOApi>(getSandboxPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSandboxEnvironmentWriteApi),
    })
}

export const getSandboxDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_environments/${id}/`
}

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const sandboxDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getSandboxDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTaskAutomationsListUrl = (projectId: string, params?: TaskAutomationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/task_automations/?${stringifiedParams}`
        : `/api/projects/${projectId}/task_automations/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsList = async (
    projectId: string,
    params?: TaskAutomationsListParams,
    options?: RequestInit
): Promise<PaginatedTaskAutomationDTOListApi> => {
    return apiMutator<PaginatedTaskAutomationDTOListApi>(getTaskAutomationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTaskAutomationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_automations/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsCreate = async (
    projectId: string,
    taskAutomationWriteApi: TaskAutomationWriteApi,
    options?: RequestInit
): Promise<TaskAutomationDTOApi> => {
    return apiMutator<TaskAutomationDTOApi>(getTaskAutomationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskAutomationWriteApi),
    })
}

export const getTaskAutomationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_automations/${id}/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TaskAutomationDTOApi> => {
    return apiMutator<TaskAutomationDTOApi>(getTaskAutomationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTaskAutomationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_automations/${id}/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTaskAutomationWriteApi?: PatchedTaskAutomationWriteApi,
    options?: RequestInit
): Promise<TaskAutomationDTOApi> => {
    return apiMutator<TaskAutomationDTOApi>(getTaskAutomationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskAutomationWriteApi),
    })
}

export const getTaskAutomationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_automations/${id}/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTaskAutomationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTaskAutomationsRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_automations/${id}/run/`
}

/**
 * API for managing scheduled task automations.
 */
export const taskAutomationsRunCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TaskAutomationDTOApi> => {
    return apiMutator<TaskAutomationDTOApi>(getTaskAutomationsRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getTaskChannelsListUrl = (projectId: string, params?: TaskChannelsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/task_channels/?${stringifiedParams}`
        : `/api/projects/${projectId}/task_channels/`
}

/**
 * All live public channels plus the requester's personal #me channel (created on first list).
 * @summary List channels
 */
export const taskChannelsList = async (
    projectId: string,
    params?: TaskChannelsListParams,
    options?: RequestInit
): Promise<PaginatedChannelDTOListApi> => {
    return apiMutator<PaginatedChannelDTOListApi>(getTaskChannelsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTaskChannelsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_channels/`
}

/**
 * Returns the existing public channel with the (normalized) name, creating it if needed.
 * @summary Resolve or create a public channel
 */
export const taskChannelsCreate = async (
    projectId: string,
    channelWriteApi: ChannelWriteApi,
    options?: RequestInit
): Promise<ChannelDTOApi> => {
    return apiMutator<ChannelDTOApi>(getTaskChannelsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(channelWriteApi),
    })
}

export const getTaskChannelsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. Listing lazily
 * provisions the requester's personal "#me" channel; creation is resolve-or-create
 * by normalized name so clients can map channel-like surfaces onto backend channels.
 * @summary Rename a public channel
 */
export const taskChannelsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedChannelWriteApi?: PatchedChannelWriteApi,
    options?: RequestInit
): Promise<ChannelDTOApi> => {
    return apiMutator<ChannelDTOApi>(getTaskChannelsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedChannelWriteApi),
    })
}

export const getTaskChannelsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. Listing lazily
 * provisions the requester's personal "#me" channel; creation is resolve-or-create
 * by normalized name so clients can map channel-like surfaces onto backend channels.
 * @summary Delete a public channel
 */
export const taskChannelsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTaskChannelsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTasksListUrl = (projectId: string, params?: TasksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/`
}

/**
 * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, and created_by.
 * @summary List tasks
 */
export const tasksList = async (
    projectId: string,
    params?: TasksListParams,
    options?: RequestInit
): Promise<PaginatedTaskDetailDTOListApi> => {
    return apiMutator<PaginatedTaskDetailDTOListApi>(getTasksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksCreate = async (
    projectId: string,
    taskWriteApi?: TaskWriteApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskWriteApi),
    })
}

export const getTasksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

/**
 * Retrieve a single task by ID.
 * @summary Get task
 */
export const tasksRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksUpdate = async (
    projectId: string,
    id: string,
    taskWriteApi?: TaskWriteApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskWriteApi),
    })
}

export const getTasksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTaskWriteApi?: PatchedTaskWriteApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskWriteApi),
    })
}

export const getTasksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTasksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTasksPresenceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/presence/`
}

/**
 * Idempotent upsert: marks the calling user + `device_id` as actively watching this task for the next ~60 seconds. While at least one device for the user has a non-expired presence row for this task, the push fanout will skip ALL of that user's other registered devices for task notifications — the contract is 'if any device is demonstrably watching, suppress the others'. Clients call this every ~30s while the task screen is foregrounded. `device_id` is the UUID of the caller's UserPushToken row.
 * @summary Beacon presence for a device watching this task
 */
export const tasksPresenceCreate = async (
    projectId: string,
    id: string,
    taskPresenceBeaconRequestApi: TaskPresenceBeaconRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksPresenceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskPresenceBeaconRequestApi),
    })
}

export const getTasksPresenceDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/presence/`
}

/**
 * Idempotent upsert: marks the calling user + `device_id` as actively watching this task for the next ~60 seconds. While at least one device for the user has a non-expired presence row for this task, the push fanout will skip ALL of that user's other registered devices for task notifications — the contract is 'if any device is demonstrably watching, suppress the others'. Clients call this every ~30s while the task screen is foregrounded. `device_id` is the UUID of the caller's UserPushToken row.
 * @summary Beacon presence for a device watching this task
 */
export const tasksPresenceDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTasksPresenceDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTasksRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/run/`
}

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const tasksRunCreate = async (
    projectId: string,
    id: string,
    taskRunCreateRequestSchemaApi?: TaskRunCreateRequestSchemaApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunCreateRequestSchemaApi),
    })
}

export const getTasksStagedArtifactsFinalizeUploadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/staged_artifacts/finalize_upload/`
}

/**
 * Verify staged S3 uploads and cache their metadata so they can be attached to the next run created for this task.
 * @summary Finalize staged direct uploads for task attachments
 */
export const tasksStagedArtifactsFinalizeUploadCreate = async (
    projectId: string,
    id: string,
    taskStagedArtifactsFinalizeUploadRequestApi: TaskStagedArtifactsFinalizeUploadRequestApi,
    options?: RequestInit
): Promise<TaskStagedArtifactsFinalizeUploadResponseApi> => {
    return apiMutator<TaskStagedArtifactsFinalizeUploadResponseApi>(
        getTasksStagedArtifactsFinalizeUploadCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskStagedArtifactsFinalizeUploadRequestApi),
        }
    )
}

export const getTasksStagedArtifactsPrepareUploadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/staged_artifacts/prepare_upload/`
}

/**
 * Reserve S3 object keys for task attachments before creating a new run and return presigned POST forms for direct uploads.
 * @summary Prepare staged direct uploads for task attachments
 */
export const tasksStagedArtifactsPrepareUploadCreate = async (
    projectId: string,
    id: string,
    taskStagedArtifactsPrepareUploadRequestApi: TaskStagedArtifactsPrepareUploadRequestApi,
    options?: RequestInit
): Promise<TaskStagedArtifactsPrepareUploadResponseApi> => {
    return apiMutator<TaskStagedArtifactsPrepareUploadResponseApi>(
        getTasksStagedArtifactsPrepareUploadCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskStagedArtifactsPrepareUploadRequestApi),
        }
    )
}

export const getTasksRunsListUrl = (projectId: string, taskId: string, params?: TasksRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${taskId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${taskId}/runs/`
}

/**
 * Get a list of runs for a specific task.
 * @summary List task runs
 */
export const tasksRunsList = async (
    projectId: string,
    taskId: string,
    params?: TasksRunsListParams,
    options?: RequestInit
): Promise<PaginatedTaskRunDetailDTOListApi> => {
    return apiMutator<PaginatedTaskRunDetailDTOListApi>(getTasksRunsListUrl(projectId, taskId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsCreateUrl = (projectId: string, taskId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/`
}

/**
 * Create a new run for a specific task without starting execution.
 * @summary Create task run
 */
export const tasksRunsCreate = async (
    projectId: string,
    taskId: string,
    taskRunBootstrapCreateRequestApi?: TaskRunBootstrapCreateRequestApi,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsCreateUrl(projectId, taskId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunBootstrapCreateRequestApi),
    })
}

export const getTasksRunsRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/`
}

/**
 * Retrieve a single run for a specific task.
 * @summary Get task run
 */
export const tasksRunsRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsPartialUpdateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/`
}

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Update task run
 */
export const tasksRunsPartialUpdate = async (
    projectId: string,
    taskId: string,
    id: string,
    patchedTaskRunUpdateApi?: PatchedTaskRunUpdateApi,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsPartialUpdateUrl(projectId, taskId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskRunUpdateApi),
    })
}

export const getTasksRunsAppendLogCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/append_log/`
}

/**
 * Append one or more log entries to the task run log array
 * @summary Append log entries
 */
export const tasksRunsAppendLogCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunAppendLogRequestApi: TaskRunAppendLogRequestApi,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsAppendLogCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunAppendLogRequestApi),
    })
}

export const getTasksRunsArtifactsCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/`
}

/**
 * Persist task artifacts to S3 and attach them to the run manifest.
 * @summary Upload artifacts for a task run
 */
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

export const getTasksRunsArtifactsDownloadCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/download/`
}

/**
 * Streams artifact content for a task run artifact after validating that it belongs to the run.
 * @summary Download an artifact through the backend
 */
export const tasksRunsArtifactsDownloadCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactPresignRequestApi: TaskRunArtifactPresignRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksRunsArtifactsDownloadCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunArtifactPresignRequestApi),
    })
}

export const getTasksRunsArtifactsFinalizeUploadCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/finalize_upload/`
}

/**
 * Verify directly uploaded S3 objects and attach them to the run artifact manifest.
 * @summary Finalize direct uploads for task run artifacts
 */
export const tasksRunsArtifactsFinalizeUploadCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactsFinalizeUploadRequestApi: TaskRunArtifactsFinalizeUploadRequestApi,
    options?: RequestInit
): Promise<TaskRunArtifactsFinalizeUploadResponseApi> => {
    return apiMutator<TaskRunArtifactsFinalizeUploadResponseApi>(
        getTasksRunsArtifactsFinalizeUploadCreateUrl(projectId, taskId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunArtifactsFinalizeUploadRequestApi),
        }
    )
}

export const getTasksRunsArtifactsPrepareUploadCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/prepare_upload/`
}

/**
 * Reserve S3 object keys for task artifacts and return presigned POST forms for direct uploads.
 * @summary Prepare direct uploads for task run artifacts
 */
export const tasksRunsArtifactsPrepareUploadCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactsPrepareUploadRequestApi: TaskRunArtifactsPrepareUploadRequestApi,
    options?: RequestInit
): Promise<TaskRunArtifactsPrepareUploadResponseApi> => {
    return apiMutator<TaskRunArtifactsPrepareUploadResponseApi>(
        getTasksRunsArtifactsPrepareUploadCreateUrl(projectId, taskId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunArtifactsPrepareUploadRequestApi),
        }
    )
}

export const getTasksRunsArtifactsPresignCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/presign/`
}

/**
 * Returns a temporary, signed URL that can be used to download a specific artifact.
 * @summary Generate presigned URL for an artifact
 */
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

export const getTasksRunsCommandCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/command/`
}

/**
 * Queue user_message JSON-RPC commands through the task workflow and forward sandbox control commands to the agent server. Supports user_message, cancel, close, permission_response, and set_config_option commands.
 * @summary Send command to task run
 */
export const tasksRunsCommandCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunCommandRequestApi: TaskRunCommandRequestApi,
    options?: RequestInit
): Promise<TaskRunCommandResponseApi> => {
    return apiMutator<TaskRunCommandResponseApi>(getTasksRunsCommandCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunCommandRequestApi),
    })
}

export const getTasksRunsConnectionTokenRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/connection_token/`
}

/**
 * Generate a JWT token for direct connection to the sandbox. Valid for 24 hours.
 * @summary Get sandbox connection token
 */
export const tasksRunsConnectionTokenRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<ConnectionTokenResponseApi> => {
    return apiMutator<ConnectionTokenResponseApi>(getTasksRunsConnectionTokenRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsRelayMessageCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/relay_message/`
}

/**
 * Queue a Slack relay workflow to post a run message into the mapped Slack thread.
 * @summary Relay run message to Slack
 */
export const tasksRunsRelayMessageCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunRelayMessageRequestApi: TaskRunRelayMessageRequestApi,
    options?: RequestInit
): Promise<TaskRunRelayMessageResponseApi> => {
    return apiMutator<TaskRunRelayMessageResponseApi>(getTasksRunsRelayMessageCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunRelayMessageRequestApi),
    })
}

export const getTasksRunsResumeInCloudCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/resume_in_cloud/`
}

/**
 * Resume an existing task run in a cloud sandbox. Terminates any existing workflow and starts a new one.
 * @summary Resume task run in cloud
 */
export const tasksRunsResumeInCloudCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsResumeInCloudCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
    })
}

export const getTasksRunsSessionLogsRetrieveUrl = (
    projectId: string,
    taskId: string,
    id: string,
    params?: TasksRunsSessionLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/session_logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/session_logs/`
}

/**
 * Fetch session log entries for a task run with optional filtering by timestamp, event type, and limit.
 * @summary Get filtered task run session logs
 */
export const tasksRunsSessionLogsRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    params?: TasksRunsSessionLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksRunsSessionLogsRetrieveUrl(projectId, taskId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsSetOutputPartialUpdateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/set_output/`
}

/**
 * Update the output field for a task run (e.g., PR URL, commit SHA, etc.)
 * @summary Set run output
 */
export const tasksRunsSetOutputPartialUpdate = async (
    projectId: string,
    taskId: string,
    id: string,
    patchedTaskRunSetOutputRequestApi?: PatchedTaskRunSetOutputRequestApi,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsSetOutputPartialUpdateUrl(projectId, taskId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTaskRunSetOutputRequestApi),
    })
}

export const getTasksRunsStartCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/start/`
}

/**
 * Start an existing cloud run after any initial run-scoped attachments have been uploaded.
 * @summary Start task run
 */
export const tasksRunsStartCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunStartRequestApi?: TaskRunStartRequestApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksRunsStartCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunStartRequestApi),
    })
}

export const getTasksRunsStreamRetrieveUrl = (
    projectId: string,
    taskId: string,
    id: string,
    params?: TasksRunsStreamRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/stream/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/stream/`
}

/**
 * Server-Sent Events stream of task run events. Events carry an `id:` line (a Redis stream id) usable as a resume cursor.
 *
 * The server caps each connection at 900 seconds: it emits `event: end` with `data: {"type": "rotated"}` and closes. This does NOT mean the run finished — reconnect with the `Last-Event-ID` header set to the last received event id to resume without gaps or duplicates. Only treat the stream as complete when the run itself reaches a terminal status.
 *
 * `?start=latest` consumers must also carry `Last-Event-ID` across reconnects: reconnecting without it re-resolves to the then-current latest event, silently skipping anything published while disconnected.
 *
 * **SDK consumers**: do not call the generated fetch wrapper for this path — it will buffer the entire stream. Use the URL builder (`getTasksRunsStreamRetrieveUrl`) with a streaming `fetch`/`EventSource`-style consumer and the `Last-Event-ID` header instead.
 */
export const tasksRunsStreamRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    params?: TasksRunsStreamRetrieveParams,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getTasksRunsStreamRetrieveUrl(projectId, taskId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsStreamTokenRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/stream_token/`
}

/**
 * Generate a run-scoped JWT that authorizes reading this task run's live event stream via the agent-proxy.
 * @summary Get task run stream read token
 */
export const tasksRunsStreamTokenRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<StreamReadTokenResponseApi> => {
    return apiMutator<StreamReadTokenResponseApi>(getTasksRunsStreamTokenRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksThreadMessagesListUrl = (
    projectId: string,
    taskId: string,
    params?: TasksThreadMessagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${taskId}/thread_messages/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${taskId}/thread_messages/`
}

/**
 * The task's thread in chronological order.
 * @summary List thread messages
 */
export const tasksThreadMessagesList = async (
    projectId: string,
    taskId: string,
    params?: TasksThreadMessagesListParams,
    options?: RequestInit
): Promise<PaginatedTaskThreadMessageDTOListApi> => {
    return apiMutator<PaginatedTaskThreadMessageDTOListApi>(getTasksThreadMessagesListUrl(projectId, taskId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksThreadMessagesCreateUrl = (projectId: string, taskId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/thread_messages/`
}

/**
 * API for a task's thread — the human-only side conversation around a task. Messages
 * reach the agent only via the explicit send_to_agent action, gated to the task author.
 * @summary Post a thread message
 */
export const tasksThreadMessagesCreate = async (
    projectId: string,
    taskId: string,
    taskThreadMessageWriteApi: TaskThreadMessageWriteApi,
    options?: RequestInit
): Promise<TaskThreadMessageDTOApi> => {
    return apiMutator<TaskThreadMessageDTOApi>(getTasksThreadMessagesCreateUrl(projectId, taskId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskThreadMessageWriteApi),
    })
}

export const getTasksThreadMessagesDestroyUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/thread_messages/${id}/`
}

/**
 * API for a task's thread — the human-only side conversation around a task. Messages
 * reach the agent only via the explicit send_to_agent action, gated to the task author.
 * @summary Delete own thread message
 */
export const tasksThreadMessagesDestroy = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksThreadMessagesDestroyUrl(projectId, taskId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTasksThreadMessagesSendToAgentCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/thread_messages/${id}/send_to_agent/`
}

/**
 * Task author only: forwards the message into the task's latest live run.
 * @summary Send a thread message to the agent
 */
export const tasksThreadMessagesSendToAgentCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskThreadMessageDTOApi: TaskThreadMessageDTOApi,
    options?: RequestInit
): Promise<TaskThreadMessageDTOApi> => {
    return apiMutator<TaskThreadMessageDTOApi>(getTasksThreadMessagesSendToAgentCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskThreadMessageDTOApi),
    })
}

export const getTasksRepositoriesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/repositories/`
}

/**
 * Return the set of repositories referenced by non-deleted, non-internal tasks in the current project. Used to populate repository filter pickers without being constrained by task list pagination.
 * @summary List distinct task repositories
 */
export const tasksRepositoriesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<TaskRepositoriesResponseApi> => {
    return apiMutator<TaskRepositoriesResponseApi>(getTasksRepositoriesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRepositoryReadinessRetrieveUrl = (
    projectId: string,
    params: TasksRepositoryReadinessRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/repository_readiness/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/repository_readiness/`
}

/**
 * Get autonomy readiness details for a specific repository in the current project.
 * @summary Get repository readiness
 */
export const tasksRepositoryReadinessRetrieve = async (
    projectId: string,
    params: TasksRepositoryReadinessRetrieveParams,
    options?: RequestInit
): Promise<RepositoryReadinessResponseApi> => {
    return apiMutator<RepositoryReadinessResponseApi>(getTasksRepositoryReadinessRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksSlackThreadContextRetrieveUrl = (
    projectId: string,
    params: TasksSlackThreadContextRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/slack_thread_context/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/slack_thread_context/`
}

/**
 * PostHog-internal debug tool. Resolves a Slack permalink to the linked task, its runs, the task-processing and mention-dispatch Temporal workflow ids/URLs, and presigned log URLs.
 * @summary Resolve a Slack thread to its task, runs, and Temporal workflows
 */
export const tasksSlackThreadContextRetrieve = async (
    projectId: string,
    params: TasksSlackThreadContextRetrieveParams,
    options?: RequestInit
): Promise<SlackThreadContextResponseApi> => {
    return apiMutator<SlackThreadContextResponseApi>(getTasksSlackThreadContextRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksSummariesCreateUrl = (projectId: string, params?: TasksSummariesCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/summaries/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/summaries/`
}

/**
 * Returns summary for the requested tasks: `id`, `title`, `repository`, `created_at`, `updated_at`, and the latest run's `status` and `environment`.
 * @summary Fetch task summaries by ID
 */
export const tasksSummariesCreate = async (
    projectId: string,
    taskSummariesRequestApi: TaskSummariesRequestApi,
    params?: TasksSummariesCreateParams,
    options?: RequestInit
): Promise<PaginatedTaskSummaryDTOListApi> => {
    return apiMutator<PaginatedTaskSummaryDTOListApi>(getTasksSummariesCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskSummariesRequestApi),
    })
}

export const getTasksWarmCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/warm/`
}

/**
 * Warm a full idling Run for a Code-app cloud task while the user composes: boot a sandbox, clone the repo, check out the branch, and start the agent, then idle awaiting the first message. On submit the normal create+run path transparently reuses and activates this Run; abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't belong to the team.
 * @summary Warm a task sandbox
 */
export const tasksWarmCreate = async (
    projectId: string,
    warmTaskRequestApi: WarmTaskRequestApi,
    options?: RequestInit
): Promise<WarmTaskResponseApi> => {
    return apiMutator<WarmTaskResponseApi>(getTasksWarmCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(warmTaskRequestApi),
    })
}
