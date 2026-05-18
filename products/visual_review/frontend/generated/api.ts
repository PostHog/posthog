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
    BaselineOverviewApi,
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
    RecomputeResultApi,
    RepoApi,
    ReviewStateCountsApi,
    RunApi,
    SnapshotApi,
    VisualReviewReposListParams,
    VisualReviewReposQuarantineListParams,
    VisualReviewReposRunsListParams,
    VisualReviewReposSnapshotsListParams,
    VisualReviewRunsListParams,
    VisualReviewRunsSnapshotHistoryListParams,
    VisualReviewRunsSnapshotsListParams,
    VisualReviewRunsToleratedHashesListParams,
} from './api.schemas'

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

/**
 * List all projects for the team.
 */
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

export const getVisualReviewReposCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/repos/`
}

/**
 * Create a new repo.
 */
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

export const getVisualReviewReposRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

/**
 * Get a repo by ID.
 */
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

export const getVisualReviewReposPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

/**
 * Update a repo's settings.
 */
export const visualReviewReposPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateRepoRequestInputApi?: PatchedUpdateRepoRequestInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateRepoRequestInputApi),
    })
}

export const getVisualReviewReposBaselinesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/baselines/`
}

/**
 * Snapshots overview for a repo: every identifier with a current baseline (latest non-superseded master/main run per run_type), plus tolerate counts, active quarantine state, and a 30-day stability sparkline. Capped at 5000 entries — sets `truncated` and returns the most recently active when exceeded. Filtering / faceting / search are all done client-side; this endpoint takes no filter query params.
 */
export const visualReviewReposBaselinesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BaselineOverviewApi> => {
    return apiMutator<BaselineOverviewApi>(getVisualReviewReposBaselinesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

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

/**
 * List quarantined identifiers. Without filter: active only. With identifier: full history.
 */
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

export const getVisualReviewReposQuarantineCreateUrl = (projectId: string, id: string, runType: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/${runType}/`
}

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
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

export const getVisualReviewReposQuarantineExpireCreateUrl = (projectId: string, id: string, runType: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/quarantine/${runType}/expire/`
}

/**
 * Expire all active quarantine entries for an identifier.
 */
export const visualReviewReposQuarantineExpireCreate = async (
    projectId: string,
    id: string,
    runType: string,
    quarantineInputApi: QuarantineInputApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getVisualReviewReposQuarantineExpireCreateUrl(projectId, id, runType), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(quarantineInputApi),
    })
}

export const getVisualReviewReposThumbnailsRetrieveUrl = (projectId: string, id: string, identifier: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/thumbnails/${identifier}/`
}

/**
 * Serve a snapshot thumbnail by identifier. Returns WebP with ETag caching.
 */
export const visualReviewReposThumbnailsRetrieve = async (
    projectId: string,
    id: string,
    identifier: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getVisualReviewReposThumbnailsRetrieveUrl(projectId, id, identifier), {
        ...options,
        method: 'GET',
    })
}

export const getVisualReviewReposRunsListUrl = (
    projectId: string,
    repoId: string,
    params?: VisualReviewReposRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/${repoId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/${repoId}/runs/`
}

/**
 * List runs in this repo, optionally filtered by review state.
 */
export const visualReviewReposRunsList = async (
    projectId: string,
    repoId: string,
    params?: VisualReviewReposRunsListParams,
    options?: RequestInit
): Promise<PaginatedRunListApi> => {
    return apiMutator<PaginatedRunListApi>(getVisualReviewReposRunsListUrl(projectId, repoId, params), {
        ...options,
        method: 'GET',
    })
}

export const getVisualReviewReposRunsCountsRetrieveUrl = (projectId: string, repoId: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${repoId}/runs/counts/`
}

/**
 * Review state counts for runs in this repo.
 */
export const visualReviewReposRunsCountsRetrieve = async (
    projectId: string,
    repoId: string,
    options?: RequestInit
): Promise<ReviewStateCountsApi> => {
    return apiMutator<ReviewStateCountsApi>(getVisualReviewReposRunsCountsRetrieveUrl(projectId, repoId), {
        ...options,
        method: 'GET',
    })
}

export const getVisualReviewReposSnapshotsListUrl = (
    projectId: string,
    repoId: string,
    runType: string,
    identifier: string,
    params?: VisualReviewReposSnapshotsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/${repoId}/snapshots/${runType}/${identifier}/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/${repoId}/snapshots/${runType}/${identifier}/`
}

/**
 * Deduped baseline timeline for a snapshot identity. Newest first.
 */
export const visualReviewReposSnapshotsList = async (
    projectId: string,
    repoId: string,
    runType: string,
    identifier: string,
    params?: VisualReviewReposSnapshotsListParams,
    options?: RequestInit
): Promise<PaginatedSnapshotHistoryEntryListApi> => {
    return apiMutator<PaginatedSnapshotHistoryEntryListApi>(
        getVisualReviewReposSnapshotsListUrl(projectId, repoId, runType, identifier, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

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

/**
 * List runs for the team, optionally filtered by review state, PR number, commit SHA, or branch.
 */
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

export const getVisualReviewRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/`
}

/**
 * Create a new run from a CI manifest.
 */
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

export const getVisualReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/`
}

/**
 * Get run status and summary.
 */
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

export const getVisualReviewRunsAddSnapshotsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/add-snapshots/`
}

/**
 * Add a batch of snapshots to a pending run (shard-based flow).
 */
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

export const getVisualReviewRunsApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/approve/`
}

/**
 * Approve visual changes for snapshots in this run.

With approve_all=true, approves all changed+new snapshots and returns
signed baseline YAML. With specific snapshots, approves only those.
 */
export const visualReviewRunsApproveCreate = async (
    projectId: string,
    id: string,
    approveRunRequestInputApi?: ApproveRunRequestInputApi,
    options?: RequestInit
): Promise<AutoApproveResultApi> => {
    return apiMutator<AutoApproveResultApi>(getVisualReviewRunsApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approveRunRequestInputApi),
    })
}

export const getVisualReviewRunsCompleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/complete/`
}

/**
 * Complete a run: detect removals, verify uploads, trigger diff processing.
 */
export const visualReviewRunsCompleteCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsCompleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getVisualReviewRunsRecomputeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/recompute/`
}

/**
 * Re-evaluate quarantine and counts, update commit status, and optionally rerun the CI job.
 */
export const visualReviewRunsRecomputeCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RecomputeResultApi> => {
    return apiMutator<RecomputeResultApi>(getVisualReviewRunsRecomputeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

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

/**
 * Recent change history for a snapshot identifier across runs.
 */
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

/**
 * Get all snapshots for a run with diff results.
 */
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

export const getVisualReviewRunsTolerateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/tolerate/`
}

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
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

/**
 * List known tolerated hashes for a snapshot identifier.
 */
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

export const getVisualReviewRunsCountsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/counts/`
}

/**
 * Review state counts for the runs list.
 */
export const visualReviewRunsCountsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ReviewStateCountsApi> => {
    return apiMutator<ReviewStateCountsApi>(getVisualReviewRunsCountsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
