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
    ChannelContextGenerationApi,
    ChannelDTOApi,
    ChannelFeedMessageDTOApi,
    ChannelFeedMessageWriteApi,
    ChannelInstructionsDTOApi,
    ChannelInstructionsWriteApi,
    ChannelStarWriteApi,
    ChannelWriteApi,
    ConnectionTokenResponseApi,
    DesktopAccessResponseApi,
    DesktopBetaTermsAcceptanceDTOApi,
    LegacyDesktopAccessResponseApi,
    LoopDTOApi,
    LoopFireResultApi,
    LoopPreviewDTOApi,
    LoopPreviewRequestApi,
    LoopRunPageApi,
    LoopSkillBundlesWriteApi,
    LoopWriteApi,
    LoopsListParams,
    LoopsRunsRetrieveParams,
    LoopsTriggerCreateBodyOne,
    LoopsTriggerCreateBodyThree,
    LoopsTriggerCreateBodyTwo,
    ModelCatalogueResponseApi,
    OnboardingSessionApi,
    OnboardingSessionTestApi,
    OnboardingSessionTestResponseApi,
    PaginatedChannelDTOListApi,
    PaginatedChannelFeedMessageDTOListApi,
    PaginatedChannelInstructionsDTOListApi,
    PaginatedLoopDTOListApi,
    PaginatedSandboxCustomImageDTOListApi,
    PaginatedSandboxEnvironmentDTOListApi,
    PaginatedTaskDetailDTOListApi,
    PaginatedTaskMentionDTOListApi,
    PaginatedTaskRunDetailDTOListApi,
    PaginatedTaskSummaryDTOListApi,
    PaginatedTaskThreadMessageDTOListApi,
    PatchedChannelInstructionsWriteApi,
    PatchedChannelUpdateApi,
    PatchedLoopWriteApi,
    PatchedSandboxCustomImageUpdateApi,
    PatchedSandboxEnvironmentWriteApi,
    PatchedTaskRunSetOutputRequestApi,
    PatchedTaskRunUpdateApi,
    PatchedTaskWriteApi,
    PinnedTaskIdsResponseApi,
    ProvisionedChannelsApi,
    RepositoryReadinessResponseApi,
    SandboxComputePricingApi,
    SandboxCustomImageBuildApi,
    SandboxCustomImageDTOApi,
    SandboxCustomImageWriteApi,
    SandboxCustomImagesListParams,
    SandboxEnvironmentDTOApi,
    SandboxEnvironmentWriteApi,
    SandboxListParams,
    SlackThreadContextResponseApi,
    StreamReadTokenResponseApi,
    TaskActivityListParams,
    TaskActivityMarkReadApi,
    TaskActivityMarkReadResponseApi,
    TaskActivityPageDTOApi,
    TaskArtifactsResponseApi,
    TaskChannelsFeedListParams,
    TaskChannelsListParams,
    TaskCommentDetailApi,
    TaskCommentsResponseApi,
    TaskCreateApi,
    TaskDetailDTOApi,
    TaskHandoffRequestApi,
    TaskMentionsListParams,
    TaskPinRequestApi,
    TaskPinResponseApi,
    TaskPresenceBeaconRequestApi,
    TaskRepositoriesResponseApi,
    TaskRunAnalysisInsightRequestApi,
    TaskRunAnalysisInsightResponseApi,
    TaskRunAnalyzeResponseApi,
    TaskRunAppendLogRequestApi,
    TaskRunArtifactPresignRequestApi,
    TaskRunArtifactPresignResponseApi,
    TaskRunArtifactsDismissRequestApi,
    TaskRunArtifactsDismissResponseApi,
    TaskRunArtifactsFinalizeUploadRequestApi,
    TaskRunArtifactsFinalizeUploadResponseApi,
    TaskRunArtifactsPrepareUploadRequestApi,
    TaskRunArtifactsPrepareUploadResponseApi,
    TaskRunArtifactsUploadRequestApi,
    TaskRunArtifactsUploadResponseApi,
    TaskRunBootstrapCreateRequestApi,
    TaskRunCancelRequestApi,
    TaskRunCommandRequestApi,
    TaskRunCommandResponseApi,
    TaskRunCreateRequestSchemaApi,
    TaskRunDetailDTOApi,
    TaskRunLivingArtifactChartRequestApi,
    TaskRunLivingArtifactChartResponseApi,
    TaskRunLivingArtifactCreateRequestApi,
    TaskRunLivingArtifactEditRequestApi,
    TaskRunLivingArtifactOpenResponseApi,
    TaskRunLivingArtifactResponseApi,
    TaskRunLivingArtifactsResponseApi,
    TaskRunPeerMessageRequestApi,
    TaskRunPeerMessageResponseApi,
    TaskRunPeersResponseApi,
    TaskRunPostHogReferencesRequestApi,
    TaskRunPostHogReferencesResponseApi,
    TaskRunRelayMessageRequestApi,
    TaskRunRelayMessageResponseApi,
    TaskRunStartRequestApi,
    TaskSearchResultApi,
    TaskSessionResponseApi,
    TaskSessionSyncResponseApi,
    TaskStagedArtifactsFinalizeUploadRequestApi,
    TaskStagedArtifactsFinalizeUploadResponseApi,
    TaskStagedArtifactsPrepareUploadRequestApi,
    TaskStagedArtifactsPrepareUploadResponseApi,
    TaskSummariesRequestApi,
    TaskThreadMessageDTOApi,
    TaskThreadMessageWriteApi,
    TaskUsageResponseApi,
    TaskWriteApi,
    TasksCommentsListParams,
    TasksCommentsRetrieveParams,
    TasksListParams,
    TasksRepositoryReadinessRetrieveParams,
    TasksRunsListParams,
    TasksRunsSessionLogsRetrieveParams,
    TasksRunsStreamRetrieveParams,
    TasksSearchRetrieveParams,
    TasksSlackThreadContextRetrieveParams,
    TasksSummariesCreateParams,
    TasksThreadMessagesListParams,
    TeachingCanvasApi,
    WarmTaskRequestApi,
    WarmTaskResponseApi,
    WarmTaskResumeRequestApi,
    WarmTaskResumeResponseApi,
    WizardCloudRunDTOApi,
} from './api.schemas'

export const getCodeInvitesCheckAccessRetrieveUrl = () => {
    return `/api/code/invites/check-access/`
}

/**
 * Compatibility endpoint for released PostHog Desktop clients.
 * @summary Check PostHog Desktop access
 */
export const codeInvitesCheckAccessRetrieve = async (
    options?: RequestInit
): Promise<LegacyDesktopAccessResponseApi> => {
    return apiMutator<LegacyDesktopAccessResponseApi>(getCodeInvitesCheckAccessRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getCodeSandboxPricingListUrl = () => {
    return `/api/code/sandbox-pricing/`
}

/**
 * Get the current sandbox compute rate card and expired rate-card history.
 * @summary Get sandbox compute pricing
 */
export const codeSandboxPricingList = async (options?: RequestInit): Promise<SandboxComputePricingApi> => {
    return apiMutator<SandboxComputePricingApi>(getCodeSandboxPricingListUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopBetaTermsListUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/desktop_beta_terms/`
}

export const desktopBetaTermsList = async (
    organizationId: string,
    options?: RequestInit
): Promise<DesktopBetaTermsAcceptanceDTOApi> => {
    return apiMutator<DesktopBetaTermsAcceptanceDTOApi>(getDesktopBetaTermsListUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopBetaTermsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/desktop_beta_terms/`
}

export const desktopBetaTermsCreate = async (
    organizationId: string,
    options?: RequestInit
): Promise<DesktopBetaTermsAcceptanceDTOApi> => {
    return apiMutator<DesktopBetaTermsAcceptanceDTOApi>(getDesktopBetaTermsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
    })
}

export const getDesktopAccessRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop/access/`
}

/**
 * Evaluate Desktop access for the selected project and organization.
 * @summary Check PostHog Desktop access
 */
export const desktopAccessRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<DesktopAccessResponseApi> => {
    return apiMutator<DesktopAccessResponseApi>(getDesktopAccessRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLoopsListUrl = (projectId: string, params?: LoopsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/loops/?${stringifiedParams}`
        : `/api/projects/${projectId}/loops/`
}

/**
 * List loops visible to the caller: personal loops they own, plus every team loop. The response also carries `max_loops_per_team` and `total_loop_count` so a client can show remaining capacity and disable creation at the cap without hardcoding the limit.
 * @summary List loops
 */
export const loopsList = async (
    projectId: string,
    params?: LoopsListParams,
    options?: RequestInit
): Promise<PaginatedLoopDTOListApi> => {
    return apiMutator<PaginatedLoopDTOListApi>(getLoopsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLoopsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/loops/`
}

/**
 * API for managing loops — named, cloud-executed agent automations triggered by
 * schedule, GitHub events or authenticated API calls. See `products/tasks/docs/LOOPS.md`.
 * @summary Create a loop
 */
export const loopsCreate = async (
    projectId: string,
    loopWriteApi: LoopWriteApi,
    options?: RequestInit
): Promise<LoopDTOApi> => {
    return apiMutator<LoopDTOApi>(getLoopsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(loopWriteApi),
    })
}

export const getLoopsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/`
}

/**
 * API for managing loops — named, cloud-executed agent automations triggered by
 * schedule, GitHub events or authenticated API calls. See `products/tasks/docs/LOOPS.md`.
 * @summary Get a loop
 */
export const loopsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<LoopDTOApi> => {
    return apiMutator<LoopDTOApi>(getLoopsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLoopsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/`
}

/**
 * Partial update. Identity-bearing fields (instructions, repositories, connectors, behaviors, model config, triggers) are owner-only on team loops; name, description, notifications and enable/pause are editable by any team member.
 * @summary Update a loop
 */
export const loopsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLoopWriteApi?: PatchedLoopWriteApi,
    options?: RequestInit
): Promise<LoopDTOApi> => {
    return apiMutator<LoopDTOApi>(getLoopsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLoopWriteApi),
    })
}

export const getLoopsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/`
}

/**
 * Soft delete. Pauses every trigger's schedule. Owner or a project admin only.
 * @summary Delete a loop
 */
export const loopsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLoopsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getLoopsPreviewCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/preview/`
}

/**
 * Dry run: renders the assembled instructions and trigger context for a supplied sample payload (or a synthetic schedule fire when omitted), without creating a task, run, or any other side effect.
 * @summary Preview a loop fire
 */
export const loopsPreviewCreate = async (
    projectId: string,
    id: string,
    loopPreviewRequestApi?: LoopPreviewRequestApi,
    options?: RequestInit
): Promise<LoopPreviewDTOApi> => {
    return apiMutator<LoopPreviewDTOApi>(getLoopsPreviewCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(loopPreviewRequestApi),
    })
}

export const getLoopsRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/run/`
}

/**
 * Manual fire from the UI. Owner-only for personal loops; any team member for team loops.
 * @summary Run a loop manually
 */
export const loopsRunCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LoopFireResultApi> => {
    return apiMutator<LoopFireResultApi>(getLoopsRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getLoopsRunsRetrieveUrl = (projectId: string, id: string, params?: LoopsRunsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/loops/${id}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/loops/${id}/runs/`
}

/**
 * Run history for a loop, newest first, cursor-paginated.
 * @summary List loop runs
 */
export const loopsRunsRetrieve = async (
    projectId: string,
    id: string,
    params?: LoopsRunsRetrieveParams,
    options?: RequestInit
): Promise<LoopRunPageApi> => {
    return apiMutator<LoopRunPageApi>(getLoopsRunsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getLoopsSkillBundlesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/skill_bundles/`
}

/**
 * Replaces the loop's attached skill bundles wholesale: zipped local skills whose contents are seeded into every fired run's sandbox. Send an empty list to detach every skill. Owner-only on team loops, like other identity-bearing configuration.
 * @summary Replace a loop's skill bundles
 */
export const loopsSkillBundlesUpdate = async (
    projectId: string,
    id: string,
    loopSkillBundlesWriteApi: LoopSkillBundlesWriteApi,
    options?: RequestInit
): Promise<LoopDTOApi> => {
    return apiMutator<LoopDTOApi>(getLoopsSkillBundlesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(loopSkillBundlesWriteApi),
    })
}

export const getLoopsTriggerCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/loops/${id}/trigger/`
}

/**
 * Authenticated POST trigger for `type=api` triggers. Project secret API key auth (`loop:write` scope), project-wide. Request body (JSON, capped at 64 KB) becomes run context. Send an `Idempotency-Key` header to dedupe retries.
 * @summary Fire a loop externally
 */
export const loopsTriggerCreate = async (
    projectId: string,
    id: string,
    loopsTriggerCreateBody?: LoopsTriggerCreateBodyOne | LoopsTriggerCreateBodyTwo | LoopsTriggerCreateBodyThree,
    options?: RequestInit
): Promise<LoopFireResultApi> => {
    return apiMutator<LoopFireResultApi>(getLoopsTriggerCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        body: JSON.stringify(loopsTriggerCreateBody),
    })
}

export const getSandboxCustomImagesListUrl = (projectId: string, params?: SandboxCustomImagesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/sandbox_custom_images/?${stringifiedParams}`
        : `/api/projects/${projectId}/sandbox_custom_images/`
}

/**
 * API for custom sandbox base images, built on top of the VM sandbox base via an image-builder agent.
 *
 * Custom images only run on the Modal VM runtime, so every action is gated on the
 * `tasks-modal-vm-sandbox` flag (org-enabled with `user_created` in its origin_products payload).
 */
export const sandboxCustomImagesList = async (
    projectId: string,
    params?: SandboxCustomImagesListParams,
    options?: RequestInit
): Promise<PaginatedSandboxCustomImageDTOListApi> => {
    return apiMutator<PaginatedSandboxCustomImageDTOListApi>(getSandboxCustomImagesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSandboxCustomImagesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/`
}

/**
 * Create a draft custom image and start its interactive image-builder agent task. The returned builder_task_id points at the conversation.
 */
export const sandboxCustomImagesCreate = async (
    projectId: string,
    sandboxCustomImageWriteApi: SandboxCustomImageWriteApi,
    options?: RequestInit
): Promise<SandboxCustomImageDTOApi> => {
    return apiMutator<SandboxCustomImageDTOApi>(getSandboxCustomImagesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxCustomImageWriteApi),
    })
}

export const getSandboxCustomImagesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/${id}/`
}

/**
 * API for custom sandbox base images, built on top of the VM sandbox base via an image-builder agent.
 *
 * Custom images only run on the Modal VM runtime, so every action is gated on the
 * `tasks-modal-vm-sandbox` flag (org-enabled with `user_created` in its origin_products payload).
 */
export const sandboxCustomImagesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SandboxCustomImageDTOApi> => {
    return apiMutator<SandboxCustomImageDTOApi>(getSandboxCustomImagesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSandboxCustomImagesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/${id}/`
}

/**
 * Rename or update the description of a custom image. Only mutable metadata (name, description) is editable; the build spec and status are managed by the build flow.
 */
export const sandboxCustomImagesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSandboxCustomImageUpdateApi?: PatchedSandboxCustomImageUpdateApi,
    options?: RequestInit
): Promise<SandboxCustomImageDTOApi> => {
    return apiMutator<SandboxCustomImageDTOApi>(getSandboxCustomImagesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSandboxCustomImageUpdateApi),
    })
}

export const getSandboxCustomImagesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/${id}/`
}

/**
 * API for custom sandbox base images, built on top of the VM sandbox base via an image-builder agent.
 *
 * Custom images only run on the Modal VM runtime, so every action is gated on the
 * `tasks-modal-vm-sandbox` flag (org-enabled with `user_created` in its origin_products payload).
 */
export const sandboxCustomImagesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSandboxCustomImagesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSandboxCustomImagesBuildCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/${id}/build/`
}

/**
 * Persist the image spec (from the request body or the builder agent's sandbox), run the security scan, and on pass build and publish the image.
 */
export const sandboxCustomImagesBuildCreate = async (
    projectId: string,
    id: string,
    sandboxCustomImageBuildApi?: SandboxCustomImageBuildApi,
    options?: RequestInit
): Promise<SandboxCustomImageDTOApi> => {
    return apiMutator<SandboxCustomImageDTOApi>(getSandboxCustomImagesBuildCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxCustomImageBuildApi),
    })
}

export const getSandboxCustomImagesBuilderTaskCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/sandbox_custom_images/${id}/builder_task/`
}

/**
 * Revive (or reuse) the image's builder agent session. When the previous session has ended, a fresh one is started seeded with the stored spec — use this to update an existing image.
 */
export const sandboxCustomImagesBuilderTaskCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SandboxCustomImageDTOApi> => {
    return apiMutator<SandboxCustomImageDTOApi>(getSandboxCustomImagesBuilderTaskCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
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

export const getTaskActivityListUrl = (projectId: string, params?: TaskActivityListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/task_activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/task_activity/`
}

/**
 * Task lifecycle rows collapse per task. Comment notifications remain separate. Results are most-recent first and restricted to tasks the requester can see.
 * @summary List the requester's task activity
 */
export const taskActivityList = async (
    projectId: string,
    params?: TaskActivityListParams,
    options?: RequestInit
): Promise<TaskActivityPageDTOApi> => {
    return apiMutator<TaskActivityPageDTOApi>(getTaskActivityListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTaskActivityMarkReadCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_activity/mark_read/`
}

/**
 * Clear collapsed task activity through task timestamps and individual comment activity through activity IDs.
 * @summary Mark task activity read
 */
export const taskActivityMarkReadCreate = async (
    projectId: string,
    taskActivityMarkReadApi: TaskActivityMarkReadApi,
    options?: RequestInit
): Promise<TaskActivityMarkReadResponseApi> => {
    return apiMutator<TaskActivityMarkReadResponseApi>(getTaskActivityMarkReadCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskActivityMarkReadApi),
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
 * All live public channels plus the requester's personal #me channel when it exists, sorted by name. Listing does not provision; call provision_defaults to create the default channels.
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
 * Returns the existing public channel with the (normalized) name, creating it if needed. A channel created here is starred for the requester unless star is false. The general name returns the team's general space; names that read as a private space ("me", "personal") are rejected.
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

export const getTaskChannelsFeedListUrl = (
    projectId: string,
    channelId: string,
    params?: TaskChannelsFeedListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/task_channels/${channelId}/feed/?${stringifiedParams}`
        : `/api/projects/${projectId}/task_channels/${channelId}/feed/`
}

/**
 * A channel's system announcements in chronological order.
 * @summary List channel feed messages
 */
export const taskChannelsFeedList = async (
    projectId: string,
    channelId: string,
    params?: TaskChannelsFeedListParams,
    options?: RequestInit
): Promise<PaginatedChannelFeedMessageDTOListApi> => {
    return apiMutator<PaginatedChannelFeedMessageDTOListApi>(getTaskChannelsFeedListUrl(projectId, channelId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTaskChannelsFeedCreateUrl = (projectId: string, channelId: string) => {
    return `/api/projects/${projectId}/task_channels/${channelId}/feed/`
}

/**
 * API for a channel's system-announcement feed — durable "PostHog agent" rows
 * (context created, CONTEXT.md being built) rendered alongside the channel's task
 * cards. Read by any team member for a public channel; personal channels are owner-only.
 * @summary Post a channel feed message
 */
export const taskChannelsFeedCreate = async (
    projectId: string,
    channelId: string,
    channelFeedMessageWriteApi: ChannelFeedMessageWriteApi,
    options?: RequestInit
): Promise<ChannelFeedMessageDTOApi> => {
    return apiMutator<ChannelFeedMessageDTOApi>(getTaskChannelsFeedCreateUrl(projectId, channelId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(channelFeedMessageWriteApi),
    })
}

export const getTaskChannelsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Get a channel
 */
export const taskChannelsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ChannelDTOApi> => {
    return apiMutator<ChannelDTOApi>(getTaskChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTaskChannelsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Rename a public channel
 */
export const taskChannelsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedChannelUpdateApi?: PatchedChannelUpdateApi,
    options?: RequestInit
): Promise<ChannelDTOApi> => {
    return apiMutator<ChannelDTOApi>(getTaskChannelsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedChannelUpdateApi),
    })
}

export const getTaskChannelsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Delete a public channel
 */
export const taskChannelsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTaskChannelsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTaskChannelsContextGenerationRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/context_generation/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Get the channel's CONTEXT.md generation task
 */
export const taskChannelsContextGenerationRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ChannelContextGenerationApi> => {
    return apiMutator<ChannelContextGenerationApi>(getTaskChannelsContextGenerationRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTaskChannelsContextGenerationUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/context_generation/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Set or clear the channel's CONTEXT.md generation task
 */
export const taskChannelsContextGenerationUpdate = async (
    projectId: string,
    id: string,
    channelContextGenerationApi: ChannelContextGenerationApi,
    options?: RequestInit
): Promise<ChannelContextGenerationApi> => {
    return apiMutator<ChannelContextGenerationApi>(getTaskChannelsContextGenerationUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(channelContextGenerationApi),
    })
}

export const getTaskChannelsInstructionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/instructions/`
}

/**
 * The channel's latest CONTEXT.md instructions. A channel with no published instructions reads as a blank version 0 — publish against base_version 0 to create version 1.
 * @summary Get channel instructions
 */
export const taskChannelsInstructionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ChannelInstructionsDTOApi> => {
    return apiMutator<ChannelInstructionsDTOApi>(getTaskChannelsInstructionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTaskChannelsInstructionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/instructions/`
}

/**
 * Publish a new version of the channel's CONTEXT.md instructions. Pass base_version (the version you read) so a concurrent edit is rejected with 409 instead of overwritten.
 * @summary Publish channel instructions
 */
export const taskChannelsInstructionsUpdate = async (
    projectId: string,
    id: string,
    channelInstructionsWriteApi: ChannelInstructionsWriteApi,
    options?: RequestInit
): Promise<ChannelInstructionsDTOApi> => {
    return apiMutator<ChannelInstructionsDTOApi>(getTaskChannelsInstructionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(channelInstructionsWriteApi),
    })
}

export const getTaskChannelsInstructionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/instructions/`
}

/**
 * Publish a new version of the channel's CONTEXT.md instructions. Pass base_version (the version you read) so a concurrent edit is rejected with 409 instead of overwritten.
 * @summary Publish channel instructions
 */
export const taskChannelsInstructionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedChannelInstructionsWriteApi?: PatchedChannelInstructionsWriteApi,
    options?: RequestInit
): Promise<ChannelInstructionsDTOApi> => {
    return apiMutator<ChannelInstructionsDTOApi>(getTaskChannelsInstructionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedChannelInstructionsWriteApi),
    })
}

export const getTaskChannelsInstructionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/instructions/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Delete channel instructions
 */
export const taskChannelsInstructionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTaskChannelsInstructionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTaskChannelsInstructionsVersionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/instructions/versions/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary List channel instruction versions
 */
export const taskChannelsInstructionsVersionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PaginatedChannelInstructionsDTOListApi> => {
    return apiMutator<PaginatedChannelInstructionsDTOListApi>(
        getTaskChannelsInstructionsVersionsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getTaskChannelsStarCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/task_channels/${id}/star/`
}

/**
 * API for task channels — the shared feeds tasks are kicked off in. The
 * provision_defaults action get-or-creates the requester's personal "#me" channel and
 * the team's shared "#general" channel; creation is resolve-or-create by normalized
 * name so clients can map channel-like surfaces onto backend channels.
 * @summary Star or unstar a channel for the requesting user
 */
export const taskChannelsStarCreate = async (
    projectId: string,
    id: string,
    channelStarWriteApi: ChannelStarWriteApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTaskChannelsStarCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(channelStarWriteApi),
    })
}

export const getTaskChannelsOnboardingSessionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_channels/onboarding_session/`
}

/**
 * Open the agent session a new user lands in, in the team's #general space. Reads the company's homepage, so it takes a few seconds and is deliberately not part of provisioning, which blocks the app opening. Callers fire it without awaiting it when provision_defaults reports personal_created.
 * @summary Start a first-run onboarding session
 */
export const taskChannelsOnboardingSessionCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<OnboardingSessionApi> => {
    return apiMutator<OnboardingSessionApi>(getTaskChannelsOnboardingSessionCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTaskChannelsOnboardingSessionTestCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_channels/onboarding_session_test/`
}

/**
 * Feature-flagged test path that creates a repeatable session from explicit prompt-building inputs, in the requester's personal space.
 * @summary Start a test first-run onboarding session
 */
export const taskChannelsOnboardingSessionTestCreate = async (
    projectId: string,
    onboardingSessionTestApi?: OnboardingSessionTestApi,
    options?: RequestInit
): Promise<OnboardingSessionTestResponseApi> => {
    return apiMutator<OnboardingSessionTestResponseApi>(getTaskChannelsOnboardingSessionTestCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(onboardingSessionTestApi),
    })
}

export const getTaskChannelsProvisionDefaultsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_channels/provision_defaults/`
}

/**
 * Get-or-create the requester's personal #me channel and the team's shared #general channel, and report which of the two this call created. Idempotent.
 * @summary Provision default channels
 */
export const taskChannelsProvisionDefaultsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<ProvisionedChannelsApi> => {
    return apiMutator<ProvisionedChannelsApi>(getTaskChannelsProvisionDefaultsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTaskChannelsTeachingCanvasTestCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/task_channels/teaching_canvas_test/`
}

/**
 * Feature-flagged test path that resolves or creates the teaching canvas in the requester's personal space.
 * @summary Create the teaching canvas for testing
 */
export const taskChannelsTeachingCanvasTestCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<TeachingCanvasApi> => {
    return apiMutator<TeachingCanvasApi>(getTaskChannelsTeachingCanvasTestCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTaskMentionsListUrl = (projectId: string, params?: TaskMentionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/task_mentions/?${stringifiedParams}`
        : `/api/projects/${projectId}/task_mentions/`
}

/**
 * Thread messages that @-mention the requester, newest first, restricted to tasks they can see.
 * @summary List mentions of the requester
 */
export const taskMentionsList = async (
    projectId: string,
    params?: TaskMentionsListParams,
    options?: RequestInit
): Promise<PaginatedTaskMentionDTOListApi> => {
    return apiMutator<PaginatedTaskMentionDTOListApi>(getTaskMentionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
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
    taskCreateApi?: TaskCreateApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskCreateApi),
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

export const getTasksArtifactsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/artifacts/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksArtifactsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TaskArtifactsResponseApi> => {
    return apiMutator<TaskArtifactsResponseApi>(getTasksArtifactsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksCommentsListUrl = (projectId: string, id: string, params?: TasksCommentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${id}/comments/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${id}/comments/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksCommentsList = async (
    projectId: string,
    id: string,
    params?: TasksCommentsListParams,
    options?: RequestInit
): Promise<TaskCommentsResponseApi> => {
    return apiMutator<TaskCommentsResponseApi>(getTasksCommentsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksCommentsRetrieveUrl = (
    projectId: string,
    id: string,
    rootCommentId: string,
    params?: TasksCommentsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/${id}/comments/${rootCommentId}/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/${id}/comments/${rootCommentId}/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksCommentsRetrieve = async (
    projectId: string,
    id: string,
    rootCommentId: string,
    params?: TasksCommentsRetrieveParams,
    options?: RequestInit
): Promise<TaskCommentDetailApi> => {
    return apiMutator<TaskCommentDetailApi>(getTasksCommentsRetrieveUrl(projectId, id, rootCommentId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTasksHandoffCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/handoff/`
}

/**
 * Transfer ownership of a task to another member of the project: they take over driving it (steering, archiving, running), and future runs resolve GitHub authorship and notification recipients from them. Only the task's current owner can hand it off. Every run must be finished or canceled, and every sandbox must be shut down first. A task in a private space moves into the recipient's private space; a task in a shared space stays there.
 * @summary Hand a task off to a colleague
 */
export const tasksHandoffCreate = async (
    projectId: string,
    id: string,
    taskHandoffRequestApi: TaskHandoffRequestApi,
    options?: RequestInit
): Promise<TaskDetailDTOApi> => {
    return apiMutator<TaskDetailDTOApi>(getTasksHandoffCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskHandoffRequestApi),
    })
}

export const getTasksPinCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/pin/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const tasksPinCreate = async (
    projectId: string,
    id: string,
    taskPinRequestApi: TaskPinRequestApi,
    options?: RequestInit
): Promise<TaskPinResponseApi> => {
    return apiMutator<TaskPinResponseApi>(getTasksPinCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskPinRequestApi),
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

export const getTasksUsageRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/usage/`
}

/**
 * Return estimated model and cloud compute costs attributed to a task.
 * @summary Get task usage
 */
export const tasksUsageRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TaskUsageResponseApi> => {
    return apiMutator<TaskUsageResponseApi>(getTasksUsageRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksWarmResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${id}/warm/`
}

/**
 * Warm an idling successor for the task's latest terminal Run while the user composes the next message. The successor restores the prior snapshot when compatible and waits for the normal run endpoint to activate it. Best-effort: returns an empty body when warming is disabled, capped, or the task advanced to another Run.
 * @summary Warm a resumed task sandbox
 */
export const tasksWarmResumeCreate = async (
    projectId: string,
    id: string,
    warmTaskResumeRequestApi: WarmTaskResumeRequestApi,
    options?: RequestInit
): Promise<WarmTaskResumeResponseApi> => {
    return apiMutator<WarmTaskResumeResponseApi>(getTasksWarmResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(warmTaskResumeRequestApi),
    })
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

export const getTasksRunsAnalysisInsightCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/analysis-insight/`
}

/**
 * Store one verified inefficiency finding on a task-analysis run. Only the run's own task-bound sandbox agent may call it, and only on a task-analysis run. The findings list is server-owned: it is not writable through the run update endpoint.
 * @summary Report an analysis finding
 */
export const tasksRunsAnalysisInsightCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunAnalysisInsightRequestApi?: TaskRunAnalysisInsightRequestApi,
    options?: RequestInit
): Promise<TaskRunAnalysisInsightResponseApi> => {
    return apiMutator<TaskRunAnalysisInsightResponseApi>(getTasksRunsAnalysisInsightCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunAnalysisInsightRequestApi),
    })
}

export const getTasksRunsAnalyzeCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/analyze/`
}

/**
 * Create a PostHog-funded analysis task that reviews this run's transcript for inefficiencies and reports findings. Idempotent per run: if an analysis task already exists for this run, it is returned instead of creating another. The analysis is not billed to the customer.
 * @summary Analyze this run
 */
export const tasksRunsAnalyzeCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunAnalyzeResponseApi> => {
    return apiMutator<TaskRunAnalyzeResponseApi>(getTasksRunsAnalyzeCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
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

export const getTasksRunsArtifactsDownloadRetrieveUrl = (
    projectId: string,
    taskId: string,
    id: string,
    artifactId: string
) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/${artifactId}/download/`
}

/**
 * Redirects to a short-lived presigned URL for the artifact, so callers can share a stable link instead of a raw presigned URL.
 * @summary Download a task run artifact by id
 */
export const tasksRunsArtifactsDownloadRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    artifactId: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getTasksRunsArtifactsDownloadRetrieveUrl(projectId, taskId, id, artifactId), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsArtifactsDismissCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/dismiss/`
}

/**
 * Hides artifacts from clients without deleting them from storage, so a file dismissed by mistake can be restored.
 * @summary Dismiss or restore task run artifacts
 */
export const tasksRunsArtifactsDismissCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunArtifactsDismissRequestApi: TaskRunArtifactsDismissRequestApi,
    options?: RequestInit
): Promise<TaskRunArtifactsDismissResponseApi> => {
    return apiMutator<TaskRunArtifactsDismissResponseApi>(
        getTasksRunsArtifactsDismissCreateUrl(projectId, taskId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunArtifactsDismissRequestApi),
        }
    )
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

export const getTasksRunsArtifactsReferencesCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/artifacts/references/`
}

/**
 * Attach live PostHog object references to the run artifact manifest without uploading files.
 * @summary Register PostHog object references for a task run
 */
export const tasksRunsArtifactsReferencesCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunPostHogReferencesRequestApi: TaskRunPostHogReferencesRequestApi,
    options?: RequestInit
): Promise<TaskRunPostHogReferencesResponseApi> => {
    return apiMutator<TaskRunPostHogReferencesResponseApi>(
        getTasksRunsArtifactsReferencesCreateUrl(projectId, taskId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunPostHogReferencesRequestApi),
        }
    )
}

export const getTasksRunsCancelCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/cancel/`
}

/**
 * Stop an active cloud run. Interrupts the agent, snapshots interactive sessions for later resume, tears down the sandbox, and marks the run cancelled. Idempotent: cancelling a finished run returns it unchanged.
 * @summary Cancel task run
 */
export const tasksRunsCancelCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    taskRunCancelRequestApi?: TaskRunCancelRequestApi,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsCancelCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(taskRunCancelRequestApi),
    })
}

export const getTasksRunsClearConversationCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/clear_conversation/`
}

/**
 * Record a `/clear` boundary in a finished run's log so the next run in the chain starts with an empty conversation. Its artifacts and visible history are unaffected. Only for a finished run: an active one has an agent that owns the clear, so send `/clear` to it as an ordinary message instead.
 * @summary Clear conversation history
 */
export const tasksRunsClearConversationCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunDetailDTOApi> => {
    return apiMutator<TaskRunDetailDTOApi>(getTasksRunsClearConversationCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
    })
}

export const getTasksRunsCommandCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/command/`
}

/**
 * Queue user_message JSON-RPC commands through the task workflow and forward sandbox control commands to the agent server. Supports user_message, cancel, close, permission_response, set_config_option, mcp_response, side_question, native Pi RPC commands, and Pi queue operations.
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

export const getTasksRunsPeersRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/peers/`
}

/**
 * Agent runs this run may send messages to: cloud Pi runs of tasks created by the same user, currently in progress or queued. Discovery and send validation share one visibility policy, so a run can only message what it can list; the per-entry `sendable` flag is the liveness contract.
 * @summary List peer agent runs
 */
export const tasksRunsPeersRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunPeersResponseApi> => {
    return apiMutator<TaskRunPeersResponseApi>(getTasksRunsPeersRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsPeersMessageCreateUrl = (
    projectId: string,
    taskId: string,
    id: string,
    targetRunId: string
) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/peers/${targetRunId}/message/`
}

/**
 * Relay a message from this run to a peer agent run. The body is delivered below a server-composed provenance envelope as a queued (non-steer) turn; attachments are copied into the target run's own artifact storage. `accepted` means queued for delivery, never delivered — the sandbox handoff happens later inside the target's workflow.
 * @summary Send a message to a peer agent run
 */
export const tasksRunsPeersMessageCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    targetRunId: string,
    taskRunPeerMessageRequestApi: TaskRunPeerMessageRequestApi,
    options?: RequestInit
): Promise<TaskRunPeerMessageResponseApi> => {
    return apiMutator<TaskRunPeerMessageResponseApi>(
        getTasksRunsPeersMessageCreateUrl(projectId, taskId, id, targetRunId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunPeerMessageRequestApi),
        }
    )
}

export const getTasksRunsPreviewRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/preview/`
}

/**
 * Redirects to the PostHog dev stack running inside this run's sandbox. A fresh sandbox access token is minted on every request and carried only in the redirect target, so it is never persisted or returned in a response body. When the run has no preview, or its sandbox has stopped, this renders a short HTML page instead.
 * @summary Open the dev stack preview for a task run
 */
export const tasksRunsPreviewRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksRunsPreviewRetrieveUrl(projectId, taskId, id), {
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

export const getTasksRunsTaskSessionRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/task_session/`
}

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Get active task session storage access
 */
export const tasksRunsTaskSessionRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<TaskSessionResponseApi> => {
    return apiMutator<TaskSessionResponseApi>(getTasksRunsTaskSessionRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTasksRunsTaskSessionSyncCreateUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/task_session_sync/`
}

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Replace the active native task session
 */
export const tasksRunsTaskSessionSyncCreate = async (
    projectId: string,
    taskId: string,
    id: string,
    tasksRunsTaskSessionSyncCreateBody?: Blob,
    options?: RequestInit
): Promise<TaskSessionSyncResponseApi> => {
    return apiMutator<TaskSessionSyncResponseApi>(getTasksRunsTaskSessionSyncCreateUrl(projectId, taskId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', ...options?.headers },
        body: tasksRunsTaskSessionSyncCreateBody,
    })
}

export const getTasksRunsLivingArtifactsListUrl = (projectId: string, taskId: string, runId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/living_artifacts/`
}

/**
 * Returns stable, versioned artifact handles created by the run's task.
 * @summary List living artifacts for a task run
 */
export const tasksRunsLivingArtifactsList = async (
    projectId: string,
    taskId: string,
    runId: string,
    options?: RequestInit
): Promise<TaskRunLivingArtifactsResponseApi[]> => {
    return apiMutator<TaskRunLivingArtifactsResponseApi[]>(
        getTasksRunsLivingArtifactsListUrl(projectId, taskId, runId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getTasksRunsLivingArtifactsCreateUrl = (projectId: string, taskId: string, runId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/living_artifacts/`
}

/**
 * Create a stable, editable artifact handle from direct markdown/text content or an existing run artifact. Slack adapters deliver into the mapped Slack thread; document artifacts use external connector storage when available.
 * @summary Create a living artifact for a task run
 */
export const tasksRunsLivingArtifactsCreate = async (
    projectId: string,
    taskId: string,
    runId: string,
    taskRunLivingArtifactCreateRequestApi: TaskRunLivingArtifactCreateRequestApi,
    options?: RequestInit
): Promise<TaskRunLivingArtifactResponseApi> => {
    return apiMutator<TaskRunLivingArtifactResponseApi>(
        getTasksRunsLivingArtifactsCreateUrl(projectId, taskId, runId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunLivingArtifactCreateRequestApi),
        }
    )
}

export const getTasksRunsLivingArtifactsOpenUrl = (projectId: string, taskId: string, runId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/living_artifacts/${id}/`
}

/**
 * Return a stable living artifact handle and the current content when the adapter supports reads.
 * @summary Open a living artifact for a task run
 */
export const tasksRunsLivingArtifactsOpen = async (
    projectId: string,
    taskId: string,
    runId: string,
    id: string,
    options?: RequestInit
): Promise<TaskRunLivingArtifactOpenResponseApi> => {
    return apiMutator<TaskRunLivingArtifactOpenResponseApi>(
        getTasksRunsLivingArtifactsOpenUrl(projectId, taskId, runId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getTasksRunsLivingArtifactsEditUrl = (projectId: string, taskId: string, runId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/living_artifacts/${id}/edit/`
}

/**
 * Commit a new version to an existing living artifact handle.
 * @summary Edit a living artifact for a task run
 */
export const tasksRunsLivingArtifactsEdit = async (
    projectId: string,
    taskId: string,
    runId: string,
    id: string,
    taskRunLivingArtifactEditRequestApi?: TaskRunLivingArtifactEditRequestApi,
    options?: RequestInit
): Promise<TaskRunLivingArtifactResponseApi> => {
    return apiMutator<TaskRunLivingArtifactResponseApi>(
        getTasksRunsLivingArtifactsEditUrl(projectId, taskId, runId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunLivingArtifactEditRequestApi),
        }
    )
}

export const getTasksRunsLivingArtifactsChartUrl = (projectId: string, taskId: string, runId: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/living_artifacts/chart/`
}

/**
 * Renders a PostHog insight (ad-hoc query JSON or a saved insight) to a PNG server-side and registers it as a slack_file living artifact in one call. Blocks until the render finishes.
 * @summary Render an insight chart and attach it as a living artifact
 */
export const tasksRunsLivingArtifactsChart = async (
    projectId: string,
    taskId: string,
    runId: string,
    taskRunLivingArtifactChartRequestApi: TaskRunLivingArtifactChartRequestApi,
    options?: RequestInit
): Promise<TaskRunLivingArtifactChartResponseApi> => {
    return apiMutator<TaskRunLivingArtifactChartResponseApi>(
        getTasksRunsLivingArtifactsChartUrl(projectId, taskId, runId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(taskRunLivingArtifactChartRequestApi),
        }
    )
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

export const getTasksActiveWizardRunRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/active_wizard_run/`
}

/**
 * Returns the most recent onboarding wizard cloud run for the current project when it is still running (or completed within the last day), so the setup-progress FAB can rehydrate after a drop-flow signup that started the run server-side. Returns 204 when there is none.
 * @summary Get the team's active onboarding wizard cloud run
 */
export const tasksActiveWizardRunRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<WizardCloudRunDTOApi | void> => {
    return apiMutator<WizardCloudRunDTOApi | void>(getTasksActiveWizardRunRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTasksModelsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/models/`
}

/**
 * Return the models a task run may use, with the reasoning efforts each one supports. Derived from the live LLM gateway catalogue, so a newly released model appears without a client change. An empty list means the gateway is unreachable — clients should fall back to their own default rather than treating it as 'no models exist'.
 * @summary List available models
 */
export const tasksModelsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ModelCatalogueResponseApi> => {
    return apiMutator<ModelCatalogueResponseApi>(getTasksModelsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTasksPinnedRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tasks/pinned/`
}

/**
 * Return the visible tasks pinned by the requester in the current project.
 * @summary List pinned tasks
 */
export const tasksPinnedRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<PinnedTaskIdsResponseApi> => {
    return apiMutator<PinnedTaskIdsResponseApi>(getTasksPinnedRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
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

export const getTasksSearchRetrieveUrl = (projectId: string, params: TasksSearchRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tasks/search/?${stringifiedParams}`
        : `/api/projects/${projectId}/tasks/search/`
}

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 * @summary Search tasks, pull requests, artifacts, and spaces
 */
export const tasksSearchRetrieve = async (
    projectId: string,
    params: TasksSearchRetrieveParams,
    options?: RequestInit
): Promise<TaskSearchResultApi[]> => {
    return apiMutator<TaskSearchResultApi[]>(getTasksSearchRetrieveUrl(projectId, params), {
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
 * Warm a full idling Run for a cloud task while the user composes: boot a sandbox, clone the repo, check out the branch, and start the agent, then idle awaiting the first message. On submit the normal create+run path transparently reuses and activates this Run; abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't belong to the team.
 * @summary Warm a task sandbox
 */
export const tasksWarmCreate = async (
    projectId: string,
    warmTaskRequestApi?: WarmTaskRequestApi,
    options?: RequestInit
): Promise<WarmTaskResponseApi> => {
    return apiMutator<WarmTaskResponseApi>(getTasksWarmCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(warmTaskRequestApi),
    })
}
