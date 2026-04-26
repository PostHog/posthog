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
    AddSnapshotsInputApi,
    AddSnapshotsResultApi,
    ApproveRunRequestInputApi,
    AutoApproveResultApi,
    CreateRepoInputApi,
    CreateRunInputApi,
    CreateRunResultApi,
    MarkToleratedInputApi,
    PaginatedQuarantinedIdentifierEntryListApi,
    PaginatedRepoListApi,
    PaginatedRunListApi,
    PaginatedSnapshotHistoryEntryListApi,
    PaginatedSnapshotListApi,
    PaginatedToleratedHashEntryListApi,
    PatchedUpdateRepoRequestInputApi,
    QuarantineInputApi,
    QuarantinedIdentifierEntryApi,
    RepoApi,
    ReviewStateCountsApi,
    RunApi,
    SnapshotApi,
    VisualReviewReposListParams,
    VisualReviewReposQuarantineDestroyParams,
    VisualReviewReposQuarantineListParams,
    VisualReviewRunsListParams,
    VisualReviewRunsSnapshotHistoryListParams,
    VisualReviewRunsSnapshotsListParams,
    VisualReviewRunsToleratedHashesListParams,
} from './api.schemas'

/**
 * List all projects for the team.
 */
export const getVisualReviewReposListUrl = (projectId: string, params?: VisualReviewReposListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/`
}

export const visualReviewReposList = async (
    projectId: string,
    params?: VisualReviewReposListParams,
    options?: RequestInit
): Promise<PaginatedRepoListApi> => {
    return apiMutator<PaginatedRepoListApi>(getVisualReviewReposListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new repo.
 */
export const getVisualReviewReposCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/repos/`
}

export const visualReviewReposCreate = async (
    projectId: string,
    createRepoInputApi: CreateRepoInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRepoInputApi),
    })
}

/**
 * Get a repo by ID.
 */
export const getVisualReviewReposRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

export const visualReviewReposRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update a repo's settings.
 */
export const getVisualReviewReposPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

export const visualReviewReposPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateRepoRequestInputApi: PatchedUpdateRepoRequestInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateRepoRequestInputApi),
    })
}

/**
 * List quarantined identifiers. Without filter: active only. With identifier: full history.
 */
export const getVisualReviewReposQuarantineListUrl = (
    projectId: string,
    id: string,
    params?: VisualReviewReposQuarantineListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/`
}

export const visualReviewReposQuarantineList = async (
    projectId: string,
    id: string,
    params?: VisualReviewReposQuarantineListParams,
    options?: RequestInit
): Promise<PaginatedQuarantinedIdentifierEntryListApi> => {
    return apiMutator<PaginatedQuarantinedIdentifierEntryListApi>(
        getVisualReviewReposQuarantineListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
export const getVisualReviewReposQuarantineCreateUrl = (projectId: string, id: string, runType: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/${runType}/`
}

export const visualReviewReposQuarantineCreate = async (
    projectId: string,
    id: string,
    runType: string,
    quarantineInputApi: QuarantineInputApi,
    options?: RequestInit
): Promise<QuarantinedIdentifierEntryApi> => {
    return apiMutator<QuarantinedIdentifierEntryApi>(getVisualReviewReposQuarantineCreateUrl(projectId, id, runType), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(quarantineInputApi),
    })
}

/**
 * Remove an identifier from quarantine.
 */
export const getVisualReviewReposQuarantineDestroyUrl = (
    projectId: string,
    id: string,
    runType: string,
    params: VisualReviewReposQuarantineDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/${runType}/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/${runType}/`
}

export const visualReviewReposQuarantineDestroy = async (
    projectId: string,
    id: string,
    runType: string,
    params: VisualReviewReposQuarantineDestroyParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getVisualReviewReposQuarantineDestroyUrl(projectId, id, runType, params), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * List runs for the team, optionally filtered by review state.
 */
export const getVisualReviewRunsListUrl = (projectId: string, params?: VisualReviewRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/`
}

export const visualReviewRunsList = async (
    projectId: string,
    params?: VisualReviewRunsListParams,
    options?: RequestInit
): Promise<PaginatedRunListApi> => {
    return apiMutator<PaginatedRunListApi>(getVisualReviewRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new run from a CI manifest.
 */
export const getVisualReviewRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/`
}

export const visualReviewRunsCreate = async (
    projectId: string,
    createRunInputApi: CreateRunInputApi,
    options?: RequestInit
): Promise<CreateRunResultApi> => {
    return apiMutator<CreateRunResultApi>(getVisualReviewRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRunInputApi),
    })
}

/**
 * Get run status and summary.
 */
export const getVisualReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/`
}

export const visualReviewRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Add a batch of snapshots to a pending run (shard-based flow).
 */
export const getVisualReviewRunsAddSnapshotsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/add-snapshots/`
}

export const visualReviewRunsAddSnapshotsCreate = async (
    projectId: string,
    id: string,
    addSnapshotsInputApi: AddSnapshotsInputApi,
    options?: RequestInit
): Promise<AddSnapshotsResultApi> => {
    return apiMutator<AddSnapshotsResultApi>(getVisualReviewRunsAddSnapshotsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(addSnapshotsInputApi),
    })
}

/**
 * Approve visual changes for snapshots in this run.

With approve_all=true, approves all changed+new snapshots and returns
signed baseline YAML. With specific snapshots, approves only those.
 */
export const getVisualReviewRunsApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/approve/`
}

export const visualReviewRunsApproveCreate = async (
    projectId: string,
    id: string,
    approveRunRequestInputApi: ApproveRunRequestInputApi,
    options?: RequestInit
): Promise<AutoApproveResultApi> => {
    return apiMutator<AutoApproveResultApi>(getVisualReviewRunsApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approveRunRequestInputApi),
    })
}

/**
 * Complete a run: detect removals, verify uploads, trigger diff processing.
 */
export const getVisualReviewRunsCompleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/complete/`
}

export const visualReviewRunsCompleteCreate = async (
    projectId: string,
    id: string,
    runApi: RunApi,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsCompleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(runApi),
    })
}

/**
 * Recent change history for a snapshot identifier across runs.
 */
export const getVisualReviewRunsSnapshotHistoryListUrl = (
    projectId: string,
    id: string,
    params: VisualReviewRunsSnapshotHistoryListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/${id}/snapshot-history/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/${id}/snapshot-history/`
}

export const visualReviewRunsSnapshotHistoryList = async (
    projectId: string,
    id: string,
    params: VisualReviewRunsSnapshotHistoryListParams,
    options?: RequestInit
): Promise<PaginatedSnapshotHistoryEntryListApi> => {
    return apiMutator<PaginatedSnapshotHistoryEntryListApi>(
        getVisualReviewRunsSnapshotHistoryListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get all snapshots for a run with diff results.
 */
export const getVisualReviewRunsSnapshotsListUrl = (
    projectId: string,
    id: string,
    params?: VisualReviewRunsSnapshotsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/${id}/snapshots/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/${id}/snapshots/`
}

export const visualReviewRunsSnapshotsList = async (
    projectId: string,
    id: string,
    params?: VisualReviewRunsSnapshotsListParams,
    options?: RequestInit
): Promise<PaginatedSnapshotListApi> => {
    return apiMutator<PaginatedSnapshotListApi>(getVisualReviewRunsSnapshotsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const getVisualReviewRunsTolerateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/tolerate/`
}

export const visualReviewRunsTolerateCreate = async (
    projectId: string,
    id: string,
    markToleratedInputApi: MarkToleratedInputApi,
    options?: RequestInit
): Promise<SnapshotApi> => {
    return apiMutator<SnapshotApi>(getVisualReviewRunsTolerateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(markToleratedInputApi),
    })
}

/**
 * List known tolerated hashes for a snapshot identifier.
 */
export const getVisualReviewRunsToleratedHashesListUrl = (
    projectId: string,
    id: string,
    params: VisualReviewRunsToleratedHashesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/${id}/tolerated-hashes/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/${id}/tolerated-hashes/`
}

export const visualReviewRunsToleratedHashesList = async (
    projectId: string,
    id: string,
    params: VisualReviewRunsToleratedHashesListParams,
    options?: RequestInit
): Promise<PaginatedToleratedHashEntryListApi> => {
    return apiMutator<PaginatedToleratedHashEntryListApi>(
        getVisualReviewRunsToleratedHashesListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Review state counts for the runs list.
 */
export const getVisualReviewRunsCountsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/counts/`
}

export const visualReviewRunsCountsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewStateCountsApi> => {
    return apiMutator<ReviewStateCountsApi>(getVisualReviewRunsCountsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
